"""Deterministic check against https://www.ahu.edu.cn/."""

from __future__ import annotations

import asyncio
import json

from lob_browser.actions import Action, ErrorKind, run_action
from lob_browser.browser import BrowserSession, SessionConfig

HOME = "https://www.ahu.edu.cn/"
OVERVIEW = "https://www.ahu.edu.cn/42/list.htm"
NOTICES = "https://www.ahu.edu.cn/tzgg/list.htm"


def _require_ok(result) -> None:
    if not result.ok:
        raise SystemExit(f"expected ok: {result.model_dump()}")


def _require_error(result, kind: ErrorKind) -> None:
    if result.ok or result.error_kind is not kind:
        raise SystemExit(f"expected {kind}: {result.model_dump()}")


async def main() -> None:
    session = BrowserSession(SessionConfig(headless=True))
    try:
        await session.start()

        home = await run_action(session, Action.navigate(HOME))
        _require_ok(home)
        if "安徽大学" not in home.after.title:
            raise SystemExit(f"unexpected title: {home.after.title}")

        _require_ok(await run_action(session, Action.click('a.menu-link[href="/42/list.htm"]')))
        if OVERVIEW not in session.page.url or "学校简介" not in await session.page.title():
            raise SystemExit(f"overview click failed: {session.page.url} {await session.page.title()}")

        _require_ok(await run_action(session, Action.back()))
        if session.page.url.rstrip("/") != HOME.rstrip("/") or "安徽大学主页" not in await session.page.title():
            raise SystemExit(f"back did not restore home: {session.page.url} {await session.page.title()}")

        _require_ok(await run_action(session, Action.reload()))
        _require_ok(await run_action(session, Action.scroll(amount=1200)))
        scroll_y = await session.page.evaluate("window.scrollY")
        if scroll_y < 100:
            raise SystemExit(f"scroll did not move page: {scroll_y}")
        _require_ok(await run_action(session, Action.scroll(selector=".footer")))
        _require_ok(await run_action(session, Action.wait(50)))

        notices = await run_action(session, Action.navigate(NOTICES))
        _require_ok(notices)
        if "通知公告" not in notices.after.title:
            raise SystemExit(f"unexpected notices title: {notices.after.title}")
        _require_ok(await run_action(session, Action.type_text("input.pageNum", "2")))
        typed = await session.page.locator("input.pageNum").first.input_value()
        if typed != "2":
            raise SystemExit(f"type mismatch: {typed!r}")

        notices_tab = session.current_tab_id
        opened = await run_action(session, Action.new_tab(OVERVIEW))
        _require_ok(opened)
        overview_tab = session.current_tab_id
        if OVERVIEW not in session.page.url or overview_tab == notices_tab:
            raise SystemExit(f"new tab failed: {session.page.url} tabs={await session.list_tabs()}")
        if len(await session.list_tabs()) != 2:
            raise SystemExit(f"expected 2 tabs: {await session.list_tabs()}")

        _require_ok(await run_action(session, Action.switch_tab(notices_tab or "")))
        if session.current_tab_id != notices_tab or "通知公告" not in await session.page.title():
            raise SystemExit(f"switch tab failed: {session.current_tab_id} {await session.page.title()}")

        _require_ok(await run_action(session, Action.close_tab(overview_tab)))
        if len(await session.list_tabs()) != 1 or session.current_tab_id != notices_tab:
            raise SystemExit(f"close tab failed: {await session.list_tabs()}")

        last = await run_action(session, Action.close_tab())
        _require_error(last, ErrorKind.TAB_NOT_FOUND)
        missing_tab = await run_action(session, Action.switch_tab("deadbeef"))
        _require_error(missing_tab, ErrorKind.TAB_NOT_FOUND)

        missing = await run_action(session, Action.click("#missing-lob-browser", timeout_ms=800))
        _require_error(missing, ErrorKind.ELEMENT_NOT_FOUND)

        timed_out = await run_action(session, Action.navigate(HOME, timeout_ms=1))
        _require_error(timed_out, ErrorKind.TIMEOUT)

        await session.page.close()
        closed = await run_action(session, Action.click("a.menu-link", timeout_ms=800))
        _require_error(closed, ErrorKind.PAGE_CLOSED)

        print(
            json.dumps(
                {
                    "home": home.after.title,
                    "typed": typed,
                    "scroll_y": scroll_y,
                    "tabs": 1,
                    "missing": missing.error_kind,
                    "missing_tab": missing_tab.error_kind,
                    "last_tab": last.error_kind,
                    "timeout": timed_out.error_kind,
                    "closed": closed.error_kind,
                },
                ensure_ascii=False,
            )
        )
        print("action loop ok")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
