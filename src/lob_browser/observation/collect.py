"""Collect visible interactive elements from the current page.

Mapped from browser-use 0.13.7 DomService / ClickableElementDetector.
Simplifications: Playwright JS instead of CDP AX/DOMSnapshot; open shadow + same-origin iframe only.
"""

from __future__ import annotations

from uuid import uuid4

from lob_browser.browser import BrowserSession
from lob_browser.observation.models import BoundingBox, InteractiveElement, Observation

_MAX_ELEMENTS = 200
_TEXT_CHARS = 4000
_NAME_CHARS = 80

# language=JavaScript
COLLECT_JS = r"""() => {
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

  const visit = (root, acc) => {
    const consider = (el) => {
      if (!el || el.nodeType !== 1) return;
      if (el.shadowRoot) visit(el.shadowRoot, acc);
      if (el.tagName === 'IFRAME' || el.tagName === 'FRAME') {
        try {
          if (el.contentDocument) visit(el.contentDocument, acc);
        } catch (e) {}
      }
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

  const observationId = Math.random().toString(36).slice(2, 10);
  const elements = filtered.map((el, i) => {
    const index = i + 1;
    el.setAttribute('data-lob-obs', observationId);
    el.setAttribute('data-lob-i', String(index));
    const type = String(el.getAttribute('type') || '').toLowerCase();
    const fieldName = el.getAttribute('name');
    const htmlId = el.getAttribute('id');
    const sensitive = type === 'password' || SENSITIVE.test(fieldName || '') || SENSITIVE.test(htmlId || '');
    const r = el.getBoundingClientRect();
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
    };
  });

  const text = (document.body && document.body.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 4000);
  return { observation_id: observationId, text, elements };
}"""


def _token_estimate(text: str, elements: list[InteractiveElement]) -> int:
    chars = len(text) + sum(len(item.line()) for item in elements)
    return (chars + 3) // 4


async def observe(session: BrowserSession) -> Observation:
    page = session.page
    raw = await page.evaluate(COLLECT_JS)
    elements: list[InteractiveElement] = []
    for item in raw.get("elements", [])[:_MAX_ELEMENTS]:
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
            )
        )
    text = str(raw.get("text") or "")[:_TEXT_CHARS]
    observation = Observation(
        observation_id=str(raw.get("observation_id") or uuid4().hex[:8]),
        url=page.url,
        title=await page.title(),
        text=text,
        elements=elements,
        token_estimate=_token_estimate(text, elements),
    )
    session.set_observation(observation)
    return observation
