"""Observe https://www.ahu.edu.cn/ and act by element index."""

from __future__ import annotations

import asyncio
import json

from lob_browser.actions import Action, ErrorKind, run_action
from lob_browser.browser import BrowserSession, SessionConfig
from lob_browser.observation import observe

HOME = "https://www.ahu.edu.cn/"
OVERVIEW = "https://www.ahu.edu.cn/42/list.htm"
NOTICES = "https://www.ahu.edu.cn/tzgg/list.htm"


def _require_ok(result) -> None:
    if not result.ok:
        raise SystemExit(f"expected ok: {result.model_dump()}")


async def main() -> None:
    session = BrowserSession(SessionConfig(headless=True))
    try:
        await session.start()
        _require_ok(await run_action(session, Action.navigate(HOME)))

        first = await observe(session)
        second = await observe(session)
        overview = second.find_name("学校概况")
        if overview is None:
            raise SystemExit(f"学校概况 not in observation:\n{second.summary()}")
        same = first.find_name("学校概况")
        if same is None or same.index != overview.index:
            raise SystemExit(f"index not stable: {None if same is None else same.index} vs {overview.index}")
        if second.token_estimate <= 0:
            raise SystemExit("token estimate missing")
        if any(item.value == "" for item in second.elements if item.input_type == "password"):
            pass
        if any(item.value not in (None, "[redacted]") and item.input_type == "password" for item in second.elements):
            raise SystemExit("password value leaked")

        clicked = await run_action(
            session,
            Action.click(index=overview.index, observation_id=second.observation_id),
        )
        _require_ok(clicked)
        if OVERVIEW not in session.page.url or "学校简介" not in await session.page.title():
            raise SystemExit(f"click by index failed: {session.page.url} {await session.page.title()}")

        stale = await run_action(
            session,
            Action.click(index=overview.index, observation_id=first.observation_id, timeout_ms=800),
        )
        if stale.ok or stale.error_kind is not ErrorKind.STALE_ELEMENT:
            raise SystemExit(f"expected stale element: {stale.model_dump()}")

        _require_ok(await run_action(session, Action.navigate(NOTICES)))
        notices = await observe(session)
        page_num = next((item for item in notices.elements if item.class_name == "pageNum"), None)
        if page_num is None:
            page_num = next((item for item in notices.elements if item.tag == "input" and item.input_type == "text"), None)
        if page_num is None:
            raise SystemExit(f"page number input missing:\n{notices.summary()}")
        typed = await run_action(
            session,
            Action.type_text(index=page_num.index, text="2", observation_id=notices.observation_id),
        )
        _require_ok(typed)

        print(
            json.dumps(
                {
                    "home_elements": len(second.elements),
                    "overview_index": overview.index,
                    "token_estimate": second.token_estimate,
                    "stale": stale.error_kind,
                    "typed_index": page_num.index,
                },
                ensure_ascii=False,
            )
        )
        print("observation ok")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
