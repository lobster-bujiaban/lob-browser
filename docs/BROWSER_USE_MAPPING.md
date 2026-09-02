# browser-use 调用链映射

研究基线：browser-use 0.13.7。以下是本项目当前实现与源码概念的对应关系；Playwright 与本地 JSONL 是刻意保留的简化边界。

| browser-use 概念 | LOB Browser | 差异与原因 |
|---|---|---|
| `BrowserSession` / watchdog | `browser.session.BrowserSession` | 保留启动、CDP、Context 和清理；暂不引入 watchdog/EventBus |
| `DomService` / `selector_map` | `observation.collect.observe` | 逐 Frame、open Shadow DOM 采集，使用观察 ID、Frame 路径和 DOM 版本 |
| `ActionResult` | `actions.models.ActionResult` | 追加标签、弹窗、下载、上传和 Frame/Shadow 元数据 |
| `DefaultActionWatchdog` | `actions.executor.run_action` | 统一动作分发、错误分类、下载/弹窗捕获和 stale 校验 |
| `Agent.step` | `agent.loop.run_task` | Observe → Decide → Validate → Act；增加退避重试、Checkpoint 和审批边界 |
| `MessageManager` / history | `agent.memory.TaskMemory` | 只保留目标、完成项、失败项和待办，避免上下文无限增长 |
| `ActionModel` / controller | `actions.models.Action` | Pydantic 动作协议，暂不做完整工具注册表 |
| `Download` / upload | `BrowserSession` 下载监听、`Action.upload` | 产物隔离、哈希、授权根目录和大小限制 |
| human-in-the-loop | `approval.ApprovalPolicy` / `ApprovalHandler` | 高风险动作执行前审批；内存实现，后续可接持久化队列 |

## 四条关键调用链

1. 页面观察：`run_task → observe → Frame.evaluate(COLLECT_JS) → Observation.elements → session.set_observation`。
2. 动作执行：`run_task → validate_decision → run_action → _target/_resolve_frame → Playwright locator → ActionResult`。
3. Agent Loop：`observe → decider → validate → approval/risk → run_action → retry/checkpoint → observe`。
4. 失败恢复：`ActionResult.error_kind → recovery_strategy → 退避 → 重新观察 → 新 observation_id/frame_version`。

## 刻意简化

- 未复制 browser-use 的完整事件总线、Watchdog、CDP AX 树和云端任务队列。
- 当前多 Agent 仅提供有界 `Planner`/`Executor` 内存协议，隔离与并发由上层编排。
- Trace 为本地 JSONL；生产部署应接 `lob-observe` 或集中式存储。
