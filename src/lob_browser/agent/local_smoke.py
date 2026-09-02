"""Run stable local form, dynamic-list, and multi-tab acceptance tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from lob_browser.actions import Action, ErrorKind, run_action
from lob_browser.agent import ApprovalStatus, Decision, LocalScriptedDecider, RetryPolicy, StaticApprovalHandler, StopReason, run_task
from lob_browser.agent.retry import recovery_strategy
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
    session = BrowserSession(
        SessionConfig(
            headless=True,
            artifact_dir=root / "artifacts",
            upload_roots=[fixtures / "files"],
        )
    )
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
        iframe_results = await _verify_iframe(session, fixtures)
        for result in iframe_results:
            writer.write("action_result", task="iframe 动作验收", result=result)
        summaries.append(
            {
                "task": "iframe 动作验收",
                "ok": True,
                "steps": len(iframe_results),
                "message": "form submitted; popup handled; stale frame index rejected",
            }
        )
        shadow_results = await _verify_shadow_dom(session, fixtures)
        for result in shadow_results:
            writer.write("action_result", task="Shadow DOM 动作验收", result=result)
        summaries.append(
            {
                "task": "Shadow DOM 动作验收",
                "ok": True,
                "steps": len(shadow_results),
                "message": "form submitted; popup handled; stale shadow index rejected",
            }
        )
        wait_results = await _verify_wait_conditions(session, fixtures)
        for result in wait_results:
            writer.write("action_result", task="业务条件等待验收", result=result)
        summaries.append(
            {
                "task": "业务条件等待验收",
                "ok": True,
                "steps": len(wait_results),
                "message": "text, selector, url, and load-state waits passed; timeout classified",
            }
        )
        upload_results = await _verify_upload(session, fixtures, root)
        for result in upload_results:
            writer.write("action_result", task="受控文件上传验收", result=result)
        summaries.append(
            {
                "task": "受控文件上传验收",
                "ok": True,
                "steps": len(upload_results),
                "message": "authorized file uploaded with sha256; unauthorized path rejected",
            }
        )
        scroll_results = await _verify_infinite_scroll(session, fixtures)
        for result in scroll_results:
            writer.write("action_result", task="无限滚动验收", result=result)
        summaries.append(
            {
                "task": "无限滚动验收",
                "ok": True,
                "steps": len(scroll_results),
                "message": "lazy target found; missing target stopped at scroll limit",
            }
        )
        download_result = await _verify_download(session, fixtures)
        writer.write("action_result", task="下载处理验收", result=download_result)
        summaries.append(
            {
                "task": "下载处理验收",
                "ok": True,
                "steps": 1,
                "message": "download saved with size and sha256",
            }
        )
        state_results, state_info = await _verify_storage_state(fixtures, root)
        for result in state_results:
            writer.write("action_result", task="登录态复用验收", result=result)
        writer.write("storage_state_saved", task="登录态复用验收", state=state_info)
        writer.write("storage_state_restored", task="登录态复用验收", ok=True, path=state_info.path)
        summaries.append(
            {
                "task": "登录态复用验收",
                "ok": True,
                "steps": 3,
                "message": "state saved and restored without exposing credential values",
            }
        )
        recovery, exhausted = await _verify_retry_recovery(session, fixtures, trace)
        summaries.append(
            {
                "task": "重新观察恢复验收",
                "ok": recovery.ok,
                "steps": len(recovery.steps),
                "message": recovery.message,
            }
        )
        summaries.append(
            {
                "task": "重试上限验收",
                "ok": exhausted.stop_reason is StopReason.RETRY_EXHAUSTED,
                "steps": len(exhausted.steps),
                "message": exhausted.message,
            }
        )
        approval_results = await _verify_approval_boundary(session, fixtures, trace)
        summaries.extend(
            {
                "task": name,
                "ok": ok,
                "steps": len(result.steps),
                "message": result.message,
            }
            for name, ok, result in approval_results
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


async def _verify_download(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "download.html").as_uri())
    observation = await observe(session)
    target = observation.find_name("下载报告")
    assert target is not None
    result = await run_action(
        session,
        Action.click(index=target.index, observation_id=observation.observation_id),
    )
    if not result.ok or len(result.downloads) != 1:
        raise SystemExit(f"download failed: {result.error}")
    download = result.downloads[0]
    source = fixtures / "files" / "lob-report.txt"
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    saved = Path(download.saved_path or "")
    expected_dir = (session.config.artifact_dir / session.session_id / "downloads").resolve()
    if saved.parent != expected_dir or not saved.is_file():
        raise SystemExit(f"download escaped artifact directory: {saved}")
    if download.size != source.stat().st_size or download.sha256 != expected_hash:
        raise SystemExit("download metadata mismatch")
    return result


async def _verify_iframe(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "iframe.html").as_uri())
    results = []
    observation = await observe(session)
    if not any(frame.path == [1] and not frame.same_origin for frame in observation.frames):
        raise SystemExit("cross-origin iframe boundary was not recorded")
    if observation.find_name("Cross Origin Button") is not None:
        raise SystemExit("cross-origin iframe DOM must not be observed")
    field = observation.find_name("iframe 姓名")
    submit = observation.find_name("iframe 提交")
    if field is None or submit is None or field.frame_path != [0] or submit.frame_path != [0]:
        raise SystemExit("iframe elements were not observed with frame_path=[0]")
    typed = await run_action(
        session,
        Action.type_text(index=field.index, text="小框", observation_id=observation.observation_id),
    )
    if not typed.ok:
        raise SystemExit(f"iframe type failed: {typed.error}")
    results.append(typed)

    observation = await observe(session)
    submit = observation.find_name("iframe 提交")
    assert submit is not None
    submitted = await run_action(
        session,
        Action.click(index=submit.index, observation_id=observation.observation_id),
    )
    if not submitted.ok:
        raise SystemExit(f"iframe submit failed: {submitted.error}")
    results.append(submitted)
    if "iframe 提交成功" not in (await observe(session)).text:
        raise SystemExit("iframe success text missing")

    observation = await observe(session)
    detail = observation.find_name("iframe 详情")
    assert detail is not None
    opened = await run_action(
        session,
        Action.click(index=detail.index, observation_id=observation.observation_id),
    )
    if not opened.ok or len(opened.opened_tabs) != 1:
        raise SystemExit(f"iframe popup failed: {opened.error}")
    results.append(opened)
    original_id = opened.switched_from_tab_id
    popup_id = opened.opened_tabs[0].tab_id
    assert original_id is not None
    results.append(await run_action(session, Action.switch_tab(original_id)))
    results.append(await run_action(session, Action.close_tab(popup_id)))

    old = await observe(session)
    old_field = old.find_name("iframe 姓名")
    assert old_field is not None
    await session.page.locator("#demo").evaluate("el => { el.src = 'iframe-content.html?reload=1' }")
    await session.page.frame_locator("#demo").locator("body").wait_for()
    stale = await run_action(
        session,
        Action.click(index=old_field.index, observation_id=old.observation_id, timeout_ms=500),
    )
    if stale.error_kind is not ErrorKind.STALE_ELEMENT:
        raise SystemExit(f"expected stale iframe index, got {stale.error_kind}")
    results.append(stale)
    return results


async def _verify_shadow_dom(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "shadow.html").as_uri())
    results = []
    observation = await observe(session)
    field = observation.find_name("Shadow 姓名")
    if field is None or field.shadow_path != ["#shadow-task"]:
        raise SystemExit("shadow element path was not observed")
    typed = await run_action(
        session,
        Action.type_text(index=field.index, text="小影", observation_id=observation.observation_id),
    )
    if not typed.ok:
        raise SystemExit(f"shadow type failed: {typed.error}")
    results.append(typed)

    observation = await observe(session)
    submit = observation.find_name("Shadow 提交")
    assert submit is not None
    submitted = await run_action(
        session,
        Action.click(index=submit.index, observation_id=observation.observation_id),
    )
    if not submitted.ok or "Shadow 提交成功" not in (await observe(session)).text:
        raise SystemExit(f"shadow submit failed: {submitted.error}")
    results.append(submitted)

    observation = await observe(session)
    detail = observation.find_name("Shadow 详情")
    assert detail is not None
    opened = await run_action(
        session,
        Action.click(index=detail.index, observation_id=observation.observation_id),
    )
    if not opened.ok or len(opened.opened_tabs) != 1:
        raise SystemExit(f"shadow popup failed: {opened.error}")
    results.append(opened)
    original_id = opened.switched_from_tab_id
    popup_id = opened.opened_tabs[0].tab_id
    assert original_id is not None
    results.append(await run_action(session, Action.switch_tab(original_id)))
    results.append(await run_action(session, Action.close_tab(popup_id)))

    old = await observe(session)
    old_field = old.find_name("Shadow 姓名")
    assert old_field is not None
    await session.page.evaluate(
        "() => document.querySelector('#shadow-task').shadowRoot.querySelector('input').replaceWith(document.createElement('input'))"
    )
    stale = await run_action(
        session,
        Action.click(index=old_field.index, observation_id=old.observation_id, timeout_ms=500),
    )
    if stale.error_kind is not ErrorKind.STALE_ELEMENT:
        raise SystemExit(f"expected stale shadow index, got {stale.error_kind}")
    results.append(stale)
    return results


async def _verify_wait_conditions(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "conditions.html").as_uri())
    results = []
    observation = await observe(session)
    start = observation.find_name("开始异步处理")
    assert start is not None
    started = await run_action(
        session,
        Action.click(index=start.index, observation_id=observation.observation_id),
    )
    if not started.ok:
        raise SystemExit(f"condition trigger failed: {started.error}")
    results.append(started)

    waits = (
        Action.wait_for_text("处理完成", timeout_ms=2_000),
        Action.wait_for_selector("#ready-action", timeout_ms=2_000),
        Action.wait_for_url("#done", timeout_ms=2_000),
        Action.wait_for_load_state("load", timeout_ms=2_000),
    )
    for action in waits:
        result = await run_action(session, action)
        if not result.ok:
            raise SystemExit(f"condition wait failed: {action.wait_condition}: {result.error}")
        results.append(result)

    timed_out = await run_action(session, Action.wait_for_text("永不出现", timeout_ms=200))
    if timed_out.error_kind is not ErrorKind.TIMEOUT:
        raise SystemExit(f"expected wait timeout, got {timed_out.error_kind}")
    results.append(timed_out)
    return results


async def _verify_upload(session: BrowserSession, fixtures: Path, root: Path):
    await session.page.goto((fixtures / "upload.html").as_uri())
    observation = await observe(session)
    field = observation.find_name("上传文件")
    assert field is not None
    source = fixtures / "files" / "lob-report.txt"
    uploaded = await run_action(
        session,
        Action.upload(
            str(source),
            index=field.index,
            observation_id=observation.observation_id,
        ),
    )
    if not uploaded.ok or len(uploaded.uploads) != 1:
        raise SystemExit(f"authorized upload failed: {uploaded.error}")
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if uploaded.uploads[0].sha256 != expected_hash:
        raise SystemExit("upload sha256 mismatch")
    ready = await run_action(session, Action.wait_for_text("LOB-DOWNLOAD-001", timeout_ms=2_000))
    if not ready.ok:
        raise SystemExit(f"uploaded content was not read: {ready.error}")

    observation = await observe(session)
    field = observation.find_name("上传文件")
    assert field is not None
    denied = await run_action(
        session,
        Action.upload(
            str(root / "README.md"),
            index=field.index,
            observation_id=observation.observation_id,
        ),
    )
    if denied.error_kind is not ErrorKind.UPLOAD_NOT_ALLOWED:
        raise SystemExit(f"expected upload_not_allowed, got {denied.error_kind}")
    if recovery_strategy(denied.action, denied) is not None:
        raise SystemExit("security error must not be automatically retried")
    missing = await run_action(
        session,
        Action.upload(
            str(fixtures / "files" / "missing.txt"),
            index=field.index,
            observation_id=observation.observation_id,
        ),
    )
    if missing.error_kind is not ErrorKind.UPLOAD_FILE_ERROR:
        raise SystemExit(f"expected upload_file_error, got {missing.error_kind}")
    return [uploaded, ready, denied, missing]


async def _verify_infinite_scroll(session: BrowserSession, fixtures: Path):
    await session.page.goto((fixtures / "infinite.html").as_uri())
    found = await run_action(
        session,
        Action.scroll_until_selector(
            "#target-record",
            amount=700,
            max_scrolls=6,
            settle_ms=120,
            timeout_ms=3_000,
        ),
    )
    if not found.ok or "目标记录 LOB-042" not in (await observe(session)).text:
        raise SystemExit(f"infinite scroll target failed: {found.error}")

    await session.page.goto((fixtures / "infinite.html").as_uri())
    limited = await run_action(
        session,
        Action.scroll_until_text(
            "不存在的记录",
            amount=300,
            max_scrolls=2,
            settle_ms=50,
            timeout_ms=1_000,
        ),
    )
    if limited.error_kind is not ErrorKind.SCROLL_LIMIT:
        raise SystemExit(f"expected scroll_limit, got {limited.error_kind}")
    return [found, limited]


async def _verify_storage_state(fixtures: Path, root: Path):
    page_bytes = (fixtures / "state.html").read_bytes()
    server = await asyncio.start_server(
        lambda reader, writer: _serve_fixture(reader, writer, page_bytes),
        "127.0.0.1",
        0,
    )
    port = server.sockets[0].getsockname()[1]
    url = f"http://127.0.0.1:{port}/state.html"
    first = BrowserSession(SessionConfig(headless=True, artifact_dir=root / "artifacts"))
    results = []
    try:
        await first.start()
        await first.page.goto(url)
        observation = await observe(first)
        login = observation.find_name("模拟登录")
        assert login is not None
        clicked = await run_action(
            first,
            Action.click(index=login.index, observation_id=observation.observation_id),
        )
        if not clicked.ok:
            raise SystemExit(f"state setup failed: {clicked.error}")
        results.append(clicked)
        ready = await run_action(first, Action.wait_for_text("登录态已恢复", timeout_ms=2_000))
        if not ready.ok:
            raise SystemExit(f"state setup confirmation failed: {ready.error}")
        results.append(ready)
        state_info = await first.save_storage_state()
    finally:
        await first.close()

    second = BrowserSession(
        SessionConfig(
            headless=True,
            artifact_dir=root / "artifacts",
            storage_state_path=Path(state_info.path),
        )
    )
    try:
        await second.start()
        await second.page.goto(url)
        restored = await run_action(second, Action.wait_for_text("登录态已恢复", timeout_ms=2_000))
        if not restored.ok:
            raise SystemExit(f"storage state restore failed: {restored.error}")
        results.append(restored)
    finally:
        await second.close()
        server.close()
        await server.wait_closed()
    return results, state_info


async def _verify_retry_recovery(session: BrowserSession, fixtures: Path, trace: Path):
    await session.page.goto((fixtures / "recovery.html").as_uri())
    first_attempt = True

    async def decider(task, observation, history):
        nonlocal first_attempt
        if "恢复成功" in observation.text:
            return Decision(done=True, success=True, message="stale element recovered")
        target = observation.find_name("执行恢复目标")
        if target is None:
            return Decision(done=True, success=False, message="recovery target missing")
        if first_attempt:
            first_attempt = False
            await session.page.evaluate(
                "() => document.querySelector('#target').replaceWith(document.querySelector('#target').cloneNode(true))"
            )
        return Decision(
            action=Action.click(index=target.index, observation_id=observation.observation_id),
            thought="click recovery target",
        )

    result = await run_task(
        session,
        "元素替换后重新观察并恢复",
        decider,
        max_steps=5,
        retry_policy=RetryPolicy(max_retries=2, base_backoff_ms=10),
        trace_path=trace,
    )
    if not result.ok or len(result.steps) != 3:
        raise SystemExit(f"retry recovery failed: {result.message}")
    failed, retried = result.steps[0], result.steps[1]
    if failed.result is None or failed.result.error_kind is not ErrorKind.STALE_ELEMENT:
        raise SystemExit("first recovery attempt must fail with stale_element")
    if retried.retry_attempt != 1 or retried.retry_of_step != 1 or not retried.result or not retried.result.ok:
        raise SystemExit("retry metadata or successful retry missing")

    await session.page.goto((fixtures / "recovery.html").as_uri())

    async def always_stale(task, observation, history):
        target = observation.find_name("执行恢复目标")
        assert target is not None
        await session.page.evaluate(
            "() => document.querySelector('#target').replaceWith(document.querySelector('#target').cloneNode(true))"
        )
        return Decision(
            action=Action.click(index=target.index, observation_id=observation.observation_id),
            thought="force stale target",
        )

    exhausted = await run_task(
        session,
        "持续元素失效直到重试上限",
        always_stale,
        max_steps=5,
        retry_policy=RetryPolicy(max_retries=1, base_backoff_ms=10),
        trace_path=trace,
    )
    if exhausted.stop_reason is not StopReason.RETRY_EXHAUSTED or len(exhausted.steps) != 2:
        raise SystemExit(f"retry limit was not enforced: {exhausted.stop_reason}")
    return result, exhausted


async def _verify_approval_boundary(session: BrowserSession, fixtures: Path, trace: Path):
    async def decider(task, observation, history):
        if "文章已发布" in observation.text:
            return Decision(done=True, success=True, message="approved publish completed")
        target = observation.find_name("发布文章")
        assert target is not None
        return Decision(
            action=Action.click(index=target.index, observation_id=observation.observation_id),
            thought="publish article",
        )

    cases = (
        ("审批暂停验收", None, StopReason.APPROVAL_REQUIRED),
        ("审批拒绝验收", StaticApprovalHandler(ApprovalStatus.REJECTED), StopReason.APPROVAL_REJECTED),
        ("审批取消验收", StaticApprovalHandler(ApprovalStatus.CANCELLED), StopReason.CANCELLED),
        ("审批批准验收", StaticApprovalHandler(ApprovalStatus.APPROVED), StopReason.DONE),
    )
    results = []
    for name, handler, expected_stop in cases:
        await session.page.goto((fixtures / "approval.html").as_uri())
        result = await run_task(
            session,
            "发布文章",
            decider,
            max_steps=4,
            approval_handler=handler,
            trace_path=trace,
        )
        if result.stop_reason is not expected_stop or len(result.approvals) != 1:
            raise SystemExit(f"approval case failed: {name}: {result.stop_reason}")
        published = "文章已发布" in (await observe(session)).text
        should_publish = expected_stop is StopReason.DONE
        if published is not should_publish:
            raise SystemExit(f"approval execution boundary failed: {name}")
        results.append((name, True, result))
    return results


async def _serve_fixture(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    body: bytes,
) -> None:
    try:
        await reader.readuntil(b"\r\n\r\n")
        headers = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/html; charset=utf-8\r\n"
            + f"Content-Length: {len(body)}\r\n".encode()
            + b"Connection: close\r\n\r\n"
        )
        writer.write(headers + body)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
