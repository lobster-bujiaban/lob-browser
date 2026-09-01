"""Run stable local form, dynamic-list, and multi-tab acceptance tasks."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from lob_browser.actions import Action, ErrorKind, run_action
from lob_browser.agent import LocalScriptedDecider, run_task
from lob_browser.agent.trace import TraceWriter
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
        dialog_results = await _verify_dialogs(session, fixtures)
        writer = TraceWriter(trace)
        for result in dialog_results:
            writer.write("action_result", task="弹窗处理验收", result=result)
        summaries.append(
            {
                "task": "弹窗处理验收",
                "ok": True,
                "steps": len(dialog_results),
                "message": "alert accepted; confirm dismissed; prompt filled; unconfigured rejected",
            }
        )
        print(json.dumps(summaries, ensure_ascii=False, indent=2))
        print(f"trace={trace}")
    finally:
        await session.close()


async def _verify_dialogs(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "dialog.html").as_uri())
    results = []
    cases = (
        ("显示 alert", Action.dialog(accept=True), "alert 已确认", "alert"),
        ("显示 confirm", Action.dialog(accept=False), "confirm 已拒绝", "confirm"),
        ("显示 prompt", Action.dialog(accept=True, prompt_text="LOB-007"), "prompt:LOB-007", "prompt"),
    )
    for name, policy, expected, dialog_type in cases:
        armed = await run_action(session, policy)
        results.append(armed)
        observation = await observe(session)
        target = observation.find_name(name)
        assert target is not None
        clicked = await run_action(
            session,
            Action.click(index=target.index, observation_id=observation.observation_id),
        )
        if not clicked.ok or not clicked.dialogs or clicked.dialogs[0].type != dialog_type:
            raise SystemExit(f"dialog case failed: {name}: {clicked.error}")
        if expected not in (await session.page.inner_text("#result")):
            raise SystemExit(f"dialog result mismatch: {name}")
        results.append(clicked)

    observation = await observe(session)
    target = observation.find_name("未配置弹窗")
    assert target is not None
    unconfigured = await run_action(
        session,
        Action.click(index=target.index, observation_id=observation.observation_id),
    )
    if unconfigured.error_kind is not ErrorKind.DIALOG_UNHANDLED:
        raise SystemExit(f"expected dialog_unhandled, got {unconfigured.error_kind}")
    if "默认拒绝" not in (await session.page.inner_text("#result")):
        raise SystemExit("unconfigured dialog was not dismissed")
    results.append(unconfigured)
    return results


if __name__ == "__main__":
    asyncio.run(main())
