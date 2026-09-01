"""Deterministic Playwright actions with classified results.

Mapped from browser-use 0.13.7 DefaultActionWatchdog / tools.service.
Uses Playwright locators instead of CDP backendNodeId; click/type/select target visible nodes.
"""

from __future__ import annotations

import asyncio
import logging
import time

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeout

from lob_browser.actions.errors import ElementNotFoundError, PageClosedError, StaleElementError
from lob_browser.actions.models import Action, ActionKind, ActionResult, ErrorKind, PageSnapshot
from lob_browser.browser import BrowserSession, SessionNotStartedError
from lob_browser.browser.errors import TabError

logger = logging.getLogger("lob_browser.actions")

_MAX_WAIT_MS = 30_000
_SUMMARY_CHARS = 200
_CLOSED_MARKERS = (
    "target closed",
    "has been closed",
    "session closed",
    "browser has been closed",
)


async def run_action(session: BrowserSession, action: Action) -> ActionResult:
    """Execute one action and always return a classified result."""
    started = time.perf_counter()
    before = await capture_snapshot(session)
    tabs_before = await session.list_tabs() if session.started else []
    current_before = session.current_tab_id
    try:
        timeout_ms = action.timeout_ms if action.timeout_ms is not None else session.config.timeout_ms
        async with asyncio.timeout(timeout_ms / 1000 + 0.5):
            message = await _dispatch(session, action, timeout_ms)
        after = await capture_snapshot(session)
        tabs_after = await session.list_tabs()
        before_ids = {tab.tab_id for tab in tabs_before}
        opened_tabs = [tab for tab in tabs_after if tab.tab_id not in before_ids]
        current_after = session.current_tab_id
        return ActionResult(
            ok=True,
            action=action,
            elapsed_ms=_elapsed_ms(started),
            before=before,
            after=after,
            message=message,
            tabs_before=tabs_before,
            tabs_after=tabs_after,
            opened_tabs=opened_tabs,
            switched_from_tab_id=current_before if current_before != current_after else None,
            switched_to_tab_id=current_after if current_before != current_after else None,
            closed_tab_id=action.tab_id or current_before if action.kind is ActionKind.CLOSE_TAB else None,
        )
    except Exception as exc:
        kind, error = classify_error(exc)
        after = await capture_snapshot(session)
        tabs_after = await session.list_tabs() if session.started else []
        logger.info("action failed kind=%s error=%s", kind, error)
        return ActionResult(
            ok=False,
            action=action,
            error_kind=kind,
            error=error,
            elapsed_ms=_elapsed_ms(started),
            before=before,
            after=after,
            tabs_before=tabs_before,
            tabs_after=tabs_after,
        )


def require_open_page(session: BrowserSession) -> Page:
    try:
        page = session.page
    except SessionNotStartedError as exc:
        raise PageClosedError(str(exc)) from exc
    if page.is_closed():
        raise PageClosedError("page is closed")
    return page


async def capture_snapshot(session: BrowserSession) -> PageSnapshot:
    try:
        page = require_open_page(session)
    except PageClosedError:
        return PageSnapshot()
    try:
        text = await page.inner_text("body")
        summary = " ".join(text.split())[:_SUMMARY_CHARS]
        return PageSnapshot(url=page.url, title=await page.title(), summary=summary)
    except PlaywrightError:
        return PageSnapshot(url=page.url)


def classify_error(exc: BaseException) -> tuple[ErrorKind, str]:
    if isinstance(exc, (PageClosedError, SessionNotStartedError)) or _is_page_closed(exc):
        return ErrorKind.PAGE_CLOSED, str(exc)
    if isinstance(exc, StaleElementError):
        return ErrorKind.STALE_ELEMENT, str(exc)
    if isinstance(exc, ElementNotFoundError):
        return ErrorKind.ELEMENT_NOT_FOUND, str(exc)
    if isinstance(exc, TabError):
        return ErrorKind.TAB_NOT_FOUND, str(exc)
    if isinstance(exc, (TimeoutError, PlaywrightTimeout)):
        return ErrorKind.TIMEOUT, str(exc)
    return ErrorKind.UNKNOWN, f"{type(exc).__name__}: {exc}"


async def _dispatch(session: BrowserSession, action: Action, timeout_ms: float) -> str:
    if action.kind is ActionKind.NEW_TAB:
        if not session.started:
            raise PageClosedError("session is not started")
        info = await session.new_tab(action.url, timeout_ms=timeout_ms)
        return f"opened tab {info.tab_id}"
    if action.kind is ActionKind.SWITCH_TAB:
        info = await session.switch_tab(action.tab_id or "")
        return f"switched to {info.tab_id}"
    if action.kind is ActionKind.CLOSE_TAB:
        closed_id = await session.close_tab(action.tab_id)
        return f"closed tab {closed_id}"

    page = require_open_page(session)
    if page.is_closed():
        raise PageClosedError("page is closed")
    match action.kind:
        case ActionKind.NAVIGATE:
            await page.goto(action.url, wait_until="domcontentloaded", timeout=timeout_ms)
            return f"navigated to {action.url}"
        case ActionKind.BACK:
            await page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
            return "navigated back"
        case ActionKind.RELOAD:
            await page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
            return "reloaded"
        case ActionKind.CLICK:
            previous_tab_ids = session.tab_ids()
            await (await _target(session, page, action, timeout_ms)).click(timeout=timeout_ms)
            opened = await session.focus_new_tab(previous_tab_ids, timeout_ms=timeout_ms)
            if opened:
                return f"clicked {action.selector or action.index}; opened and switched to tab {opened.tab_id}"
            return f"clicked {action.selector or action.index}"
        case ActionKind.TYPE:
            locator = await _target(session, page, action, timeout_ms)
            if action.clear:
                await locator.fill(action.text or "", timeout=timeout_ms)
            else:
                await locator.press_sequentially(action.text or "", timeout=timeout_ms)
            return f"typed into {action.selector or action.index}"
        case ActionKind.SELECT:
            await (await _target(session, page, action, timeout_ms)).select_option(
                value=action.value,
                timeout=timeout_ms,
            )
            return f"selected {action.value} on {action.selector or action.index}"
        case ActionKind.SCROLL:
            if action.selector or action.index is not None:
                await (await _target(session, page, action, timeout_ms)).scroll_into_view_if_needed(
                    timeout=timeout_ms,
                )
                return f"scrolled {action.selector or action.index} into view"
            delta = action.amount if action.amount is not None else 800
            if action.direction == "up":
                delta = -abs(delta)
            await page.evaluate("amount => window.scrollBy(0, amount)", delta)
            return f"scrolled {action.direction} by {abs(delta)}"
        case ActionKind.WAIT:
            duration_ms = min(max(action.duration_ms or 1000, 0), _MAX_WAIT_MS)
            await asyncio.sleep(duration_ms / 1000)
            return f"waited {duration_ms}ms"


async def _target(session: BrowserSession, page: Page, action: Action, timeout_ms: float):
    if action.index is None:
        return await _attached(page, action.selector, timeout_ms)
    observation = session.observation
    if observation is None:
        raise StaleElementError("no observation")
    if action.observation_id and action.observation_id != observation.observation_id:
        raise StaleElementError("observation_id mismatch")
    if _normalize_url(page.url) != _normalize_url(observation.url):
        raise StaleElementError("page changed since observation")
    page_version = await page.evaluate("() => window.__lobPageVersion || 0")
    if page_version != observation.page_version:
        raise StaleElementError("DOM changed since observation")
    if observation.element(action.index) is None:
        raise ElementNotFoundError(f"index={action.index}")
    selector = f'[data-lob-obs="{observation.observation_id}"][data-lob-i="{action.index}"]'
    try:
        return await _attached(page, selector, timeout_ms)
    except ElementNotFoundError as exc:
        raise StaleElementError(f"index {action.index} is stale") from exc


async def _attached(page: Page, selector: str | None, timeout_ms: float):
    if not selector:
        raise ElementNotFoundError("<empty>")
    locator = page.locator(selector).filter(visible=True)
    try:
        await locator.first.wait_for(state="visible", timeout=timeout_ms)
    except PlaywrightTimeout as exc:
        raise ElementNotFoundError(selector) from exc
    return locator.first


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


def _is_page_closed(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(marker in message for marker in _CLOSED_MARKERS)


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
