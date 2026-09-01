"""Run three AHU tasks through Observe → Decide → Validate → Act."""

from __future__ import annotations

import asyncio
import json

from lob_browser.agent import ScriptedDecider, run_task
from lob_browser.browser import BrowserSession, SessionConfig

TASKS = (
    "打开学校概况并确认进入学校简介",
    "打开通知公告列表",
    "在通知公告页将页码填为 2",
)


async def main() -> None:
    decider = ScriptedDecider()
    session = BrowserSession(SessionConfig(headless=True))
    results = []
    try:
        await session.start()
        for task in TASKS:
            result = await run_task(session, task, decider, max_steps=8)
            results.append(
                {
                    "task": task,
                    "ok": result.ok,
                    "stop_reason": result.stop_reason,
                    "steps": len(result.steps),
                    "last_url": result.steps[-1].url if result.steps else "",
                    "message": result.message,
                }
            )
            if not result.ok:
                raise SystemExit(json.dumps(results, ensure_ascii=False, indent=2))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        print("agent loop ok")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
