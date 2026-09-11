"""Collect visible interactive elements from the current page.

Mapped from browser-use 0.13.7 DomService / ClickableElementDetector.
Simplifications: Playwright JS instead of CDP AX/DOMSnapshot; open shadow + same-origin iframe only.
"""

from __future__ import annotations

from urllib.parse import urlsplit
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Frame

from lob_browser.browser import BrowserSession
from lob_browser.observation.models import BoundingBox, FrameInfo, InteractiveElement, Observation

_MAX_ELEMENTS = 200
_TEXT_CHARS = 4000
_NAME_CHARS = 80

# language=JavaScript
COLLECT_JS = r"""({observationId, startIndex}) => {
  const INTERACTIVE = new Set(['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY']);
  const ROLES = new Set(['button', 'link', 'textbox', 'menuitem', 'tab', 'checkbox', 'radio', 'combobox', 'searchbox']);
  const SENSITIVE = /password|passwd|secret|token|credit|card|cvv|ssn/i;

  const visible = (el) => {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden' || Number(st.opacity) === 0) return false;
    if (el.getAttribute('aria-hidden') === 'true') return false;
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return false;
    if (r.bottom <= 0 || r.right <= 0 || r.left >= innerWidth) return false;
    return true;
  };

  const occluded = (el) => {
    const r = el.getBoundingClientRect();
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!top) return false;
    let root = el.getRootNode();
    while (root instanceof ShadowRoot) {
      if (top === root.host) return false;
      root = root.host.getRootNode();
    }
    return top !== el && !el.contains(top);
  };

  const disabled = (el) => Boolean(el.disabled) || el.getAttribute('aria-disabled') === 'true';

  const accessibleName = (el) => {
    const raw = el.getAttribute('aria-label') || el.getAttribute('title') || el.innerText || el.placeholder || '';
    return String(raw).replace(/\s+/g, ' ').trim().slice(0, 80);
  };

  const isInteractive = (el) => {
    const tag = el.tagName;
    if (INTERACTIVE.has(tag)) {
      if (tag === 'A' && !el.getAttribute('href')) return false;
      if (tag === 'INPUT' && String(el.type || '').toLowerCase() === 'hidden') return false;
      return true;
    }
    const role = (el.getAttribute('role') || '').toLowerCase();
    if (ROLES.has(role)) return true;
    return Boolean(el.isContentEditable);
  };

  if (!window.__lobPageVersionInstalled) {
    window.__lobPageVersionInstalled = true;
    window.__lobPageVersion = 0;
    window.__lobObservedRoots = new WeakSet();
  }

  const installObserver = (root) => {
    if (window.__lobObservedRoots.has(root)) return;
    window.__lobObservedRoots.add(root);
    const observer = new MutationObserver((records) => {
      const meaningful = records.some((record) => {
        if (record.type !== 'attributes') return true;
        return record.attributeName !== 'data-lob-obs' && record.attributeName !== 'data-lob-i';
      });
      if (meaningful) window.__lobPageVersion += 1;
    });
    observer.observe(root, { subtree: true, childList: true, characterData: true, attributes: true });
  };

  const roots = [];

  const visit = (root, acc) => {
    installObserver(root.nodeType === 9 ? root.documentElement : root);
    roots.push(root);
    const consider = (el) => {
      if (!el || el.nodeType !== 1) return;
      if (el.shadowRoot) visit(el.shadowRoot, acc);
      if (isInteractive(el) && visible(el) && !disabled(el) && !occluded(el)) acc.push(el);
    };
    if (root.nodeType === 1) consider(root);
    if (!root.querySelectorAll) return;
    root.querySelectorAll('*').forEach(consider);
  };

  document.querySelectorAll('[data-lob-obs]').forEach((el) => {
    el.removeAttribute('data-lob-obs');
    el.removeAttribute('data-lob-i');
  });

  const acc = [];
  visit(document, acc);
  const set = new Set(acc);
  const filtered = acc.filter((el) => {
    let parent = el.parentElement;
    while (parent) {
      if (set.has(parent)) return false;
      parent = parent.parentElement;
    }
    return true;
  }).slice(0, 200);

  const elements = filtered.map((el, i) => {
    const index = startIndex + i;
    el.setAttribute('data-lob-obs', observationId);
    el.setAttribute('data-lob-i', String(index));
    const type = String(el.getAttribute('type') || '').toLowerCase();
    const fieldName = el.getAttribute('name');
    const htmlId = el.getAttribute('id');
    const sensitive = type === 'password' || SENSITIVE.test(fieldName || '') || SENSITIVE.test(htmlId || '');
    const r = el.getBoundingClientRect();
    const shadowPath = [];
    let root = el.getRootNode();
    while (root instanceof ShadowRoot) {
      const host = root.host;
      shadowPath.unshift(host.id ? `#${host.id}` : host.tagName.toLowerCase());
      root = host.getRootNode();
    }
    let value = null;
    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT') {
      value = sensitive ? '[redacted]' : String(el.value || '').slice(0, 40);
    }
    return {
      index,
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      name: accessibleName(el),
      field_name: fieldName,
      html_id: htmlId,
      class_name: String(el.className || '').trim().split(/\s+/)[0] || null,
      href: el.getAttribute('href'),
      input_type: type || null,
      value,
      bbox: { x: r.x, y: r.y, width: r.width, height: r.height },
      shadow_path: shadowPath,
    };
  });

  const text = roots.map((root) => root === document ? document.body?.innerText : root.textContent)
    .join(' ').replace(/\s+/g, ' ').trim().slice(0, 4000);
  return { observation_id: observationId, page_version: window.__lobPageVersion, text, elements };
}"""


def _token_estimate(text: str, elements: list[InteractiveElement]) -> int:
    chars = len(text) + sum(len(item.line()) for item in elements)
    return (chars + 3) // 4


async def observe(session: BrowserSession) -> Observation:
    page = session.page
    observation_id = uuid4().hex[:8]
    elements: list[InteractiveElement] = []
    frames: list[FrameInfo] = []
    texts: list[str] = []
    main_origin = _origin(page.url)
    main_version = 0
    for frame, frame_path in _walk_frames(page.main_frame):
        same_origin = frame is page.main_frame or _origin(frame.url) == main_origin
        frames.append(FrameInfo(path=frame_path, url=frame.url, same_origin=same_origin))
        if not same_origin:
            continue
        try:
            raw = await frame.evaluate(
                COLLECT_JS,
                {"observationId": observation_id, "startIndex": len(elements) + 1},
            )
        except PlaywrightError:
            continue
        frame_version = int(raw.get("page_version") or 0)
        if not frame_path:
            main_version = frame_version
        texts.append(str(raw.get("text") or ""))
        for item in raw.get("elements", []):
            if len(elements) >= _MAX_ELEMENTS:
                break
            bbox = item.get("bbox")
            elements.append(
                InteractiveElement(
                    index=item["index"],
                    tag=item.get("tag") or "div",
                    role=item.get("role"),
                    name=(item.get("name") or "")[:_NAME_CHARS],
                    field_name=item.get("field_name"),
                    html_id=item.get("html_id"),
                    class_name=item.get("class_name"),
                    href=item.get("href"),
                    input_type=item.get("input_type"),
                    value=item.get("value"),
                    bbox=BoundingBox.model_validate(bbox) if bbox else None,
                    frame_path=frame_path,
                    frame_url=frame.url,
                    frame_version=frame_version,
                    shadow_path=item.get("shadow_path") or [],
                )
            )
    text = " ".join(texts)[:_TEXT_CHARS]
    observation = Observation(
        observation_id=observation_id,
        page_version=main_version,
        url=page.url,
        title=await page.title(),
        text=text,
        elements=elements,
        frames=frames,
        token_estimate=_token_estimate(text, elements),
    )
    session.set_observation(observation)
    return observation


def _walk_frames(frame: Frame, path: list[int] | None = None):
    current = path or []
    yield frame, current
    for index, child in enumerate(frame.child_frames):
        yield from _walk_frames(child, [*current, index])


def _origin(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    return parsed.scheme, parsed.netloc
