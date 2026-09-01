"""Run stable local form, dynamic-list, and multi-tab acceptance tasks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lob_browser.actions import Action, ErrorKind, run_action
from lob_browser.agent import LocalScriptedDecider, run_task
from lob_browser.browser import BrowserSession, SessionConfig
from lob_browser.observation import observe

TASKS = ("完成本地表单任务", "完成本地动态列表任务", "完成本地多标签任务")


async def main() -> None:
    root = Path(__file__).resolve().parents[3]
    fixtures = root / "fixtures"
    trace = root / "artifacts" / "local-smoke.jsonl"
    trace.unlink(missing_ok=True)
    decider = LocalScriptedDecider(fixtures)
    session = BrowserSession(SessionConfig(headless=True))
    summaries = []
    try:
        await session.start()
        for task in TASKS:
            await session.page.goto((fixtures / "index.html").as_uri())
            result = await run_task(session, task, decider, max_steps=10, trace_path=trace)
            summaries.append({"task": task, "ok": result.ok, "steps": len(result.steps), "message": result.message})
            if not result.ok:
                raise SystemExit(json.dumps(summaries, ensure_ascii=False, indent=2))
        await session.page.goto((fixtures / "dynamic.html").as_uri())
        old = await observe(session)
        target = old.find_name("搜索词")
        assert target is not None
        await session.page.evaluate("() => document.querySelector('#controls').replaceChildren(document.createElement('button'))")
        stale = await run_action(
            session,
            Action.click(index=target.index, observation_id=old.observation_id, timeout_ms=500),
        )
        if stale.error_kind is not ErrorKind.STALE_ELEMENT:
            raise SystemExit(f"expected stale_element, got {stale.error_kind}")
        summaries.append({"task": "失效索引校验", "ok": True, "steps": 1, "message": stale.error})
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        print(f"trace={trace}")
    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
