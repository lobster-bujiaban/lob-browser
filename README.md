# LOB Browser

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

从 browser-use 的源码调用链出发，分阶段实现一个可观察、可恢复、可审批的浏览器 Agent，掌握页面感知、动作执行、Agent Loop、失败恢复和安全边界。

项目不以封装 Playwright 脚本为目标，而是研究浏览器状态如何进入模型上下文、模型如何选择动作、执行结果如何反馈，以及复杂网页任务如何可靠完成。

## 核心目标

- 理解 Browser、Context、Tab、Page State、Action、Step 和 Task 等领域对象。
- 建立 DOM、可交互元素、截图和页面文本的统一观察协议。
- 实现 Navigate、Click、Type、Scroll、Wait、Tab 等基础动作。
- 打通“观察 → 决策 → 执行 → 再观察 → 完成判断”的 Agent Loop。
- 处理动态页面、元素失效、跳转、弹窗、下载、上传和多标签页。
- 支持超时、重试、失败恢复、取消和运行记录回放。
- 对登录、发布、删除、支付等高风险动作建立人工审批边界。
- 定位 browser-use 对应源码入口，形成自研对象与源码对象的映射。

## 学习主链路

```text
用户任务
  → 创建浏览器会话
  → 获取页面状态
  → 压缩 DOM / 标记可交互元素
  → 模型选择动作
  → 校验并执行动作
  → 采集页面变化与执行结果
  → 判断完成 / 重试 / 请求审批
  → 保存 Trace 与最终结果
```

## 阶段路线

- [x] 阶段 0：项目定位、领域模型与实施计划
- [x] 阶段 1：浏览器会话与确定性动作闭环
- [x] 阶段 2：页面感知与可交互元素抽取
- [x] 阶段 3：模型驱动的 Browser Agent Loop
- [x] 阶段 4：动态页面、标签页与复杂交互
- [x] 阶段 5：可靠执行、恢复与人工审批
- [x] 阶段 6：记忆、任务规划与多 Agent
- [x] 阶段 7：评测、可观测与生产化
- [x] 阶段 8：browser-use 源码映射与差异清单

详细任务和验收标准见 [实施计划](./docs/IMPLEMENTATION_PLAN.md)。

## 技术基线

- Python 3.12+，使用 `uv` 管理依赖与锁文件。
- Playwright 负责浏览器控制，优先通过 Chromium CDP 研究真实执行链路。
- Pydantic 定义任务、观察、动作、步骤和事件协议。
- OpenAI-compatible 模型作为首个模型适配器。
- 首期使用进程内状态和 JSONL Trace，状态稳定后再引入 PostgreSQL 与队列。
- 固定本地测试页面验证动作语义，避免把公网网站变化当成实现问题。

## 首个可运行里程碑

输入一个固定任务，Agent 能打开本地测试页面，读取可交互元素，依次完成点击和输入，验证页面结果，并输出包含观察、动作、耗时和错误的完整步骤记录。

运行稳定的本地验收任务：

```bash
uv run python -m lob_browser.agent.local_smoke
```

命令依次验证表单、异步动态列表和多标签页，并将完整 JSONL Trace 写入 `artifacts/local-smoke.jsonl`。

多标签验收使用页面中的真实链接触发新 Page，执行器会自动注册并切换新标签；`ActionResult` 和 Trace 同时记录标签打开、切换与关闭事件。

弹窗处理通过 `Action.dialog(accept=..., prompt_text=...)` 配置下一次 alert、confirm 或 prompt；未配置策略的弹窗会被安全拒绝，并返回 `dialog_unhandled`，所有弹窗内容和处理结果都会进入 `ActionResult` 与 Trace。

下载文件保存到 `artifacts/<session_id>/downloads/`，使用安全文件名和随机前缀避免路径穿越及覆盖；`ActionResult` 与 Trace 会记录来源 URL、建议文件名、保存路径、大小和 SHA-256。

同源 iframe 会被逐 Frame 观察，元素携带 `frame_path`、Frame URL 和独立 DOM 版本；动作按路径进入目标 Frame，iframe 重载后旧索引会被拒绝。跨域 iframe 仅记录边界，不读取内部 DOM。

open Shadow DOM 会递归观察，元素携带宿主 `shadow_path`；Playwright 定位器穿透开放 Shadow Root，内部 DOM 变化会推进版本并使旧索引失效。closed Shadow Root 保持不可读边界。

等待动作除固定时长外，还支持元素可见、跨同源 Frame/开放 Shadow Root 的文本出现、URL 片段和页面加载状态；条件未在动作超时内满足时返回统一 `timeout` 结果。

文件上传默认禁止，仅允许 `SessionConfig.upload_roots` 明确授权目录中的普通文件；真实路径解析后仍需位于授权根目录并满足大小上限，上传结果记录文件名、大小和 SHA-256，越权路径返回 `upload_not_allowed`。

无限滚动支持滚动直到文本或元素出现，并通过 `max_scrolls` 与 `settle_ms` 限制次数和异步稳定窗口；目标始终未出现时返回 `scroll_limit`，不会无界滚动。

BrowserContext 可通过显式 `storage_state_path` 恢复登录态；保存状态只写入 `artifacts/<session_id>/state/` 且权限为 `0600`，对外仅返回路径、大小和 SHA-256，不读取或写入 Trace 中的 cookie/localStorage 内容。

Agent Loop 对 `stale_element` 和 `element_not_found` 使用重新观察后有限重试，对等待、滚动和导航类超时使用指数退避；可能已产生副作用的点击超时以及权限、安全错误不会自动重放。Step 与 Trace 记录重试次数、原始步骤、恢复策略和退避时间。

发布、删除、支付、发送、授权和权限变更等高风险点击在执行前生成审批请求；无处理器时以 `approval_required` 暂停，拒绝或取消时不执行，只有批准后继续。审批请求、决定、风险原因和时间写入 Step、AgentResult 与 Trace 审计记录。

## 项目边界

- `lob-browser` 关注网页任务执行，不重复实现 `lob-harness` 的通用 Agent 运行框架。
- 持久化状态机和复杂 Checkpoint 原理留给 `lob-graph`。
- Trace、Prompt 版本和系统化评测后续与 `lob-observe` 对接。
- 不绕过验证码、反爬、安全警告或网站权限边界。
- 不默认执行发布、删除、支付等有外部副作用的动作。

阶段 6～8 的入口：`TaskMemory` / `Planner` / `Executor` 提供有界任务记忆与规划协议；`EvaluationSuite` / `evaluate_suite` 提供任务集与成功率、步骤、Token、重试指标；browser-use 调用链映射见 [源码映射](./docs/BROWSER_USE_MAPPING.md)。

## Web 前端

项目附带一个浏览器 Agent 工作台原型，位于 `web/` 目录，参考同级 LOB 系列的“会话列表 + 对话区 + 执行流程”交互结构，增加了浏览器 Agent 的执行步骤、页面观察、审批确认和任务结果面板。

当前前端使用内置演示状态模拟一次表单任务，后续可将 `web/app.js` 中的 `runDemo` 替换为后端的创建任务、WebSocket/SSE 事件流和审批接口。查看方式：

```bash
python3 -m http.server 8080 --directory web
```

打开 `http://127.0.0.1:8080` 即可体验。

启动任务 API：

首次部署时，先由 PostgreSQL 管理员创建应用数据库和最小权限账号：

```bash
psql -h <host> -U postgres -d postgres \
  -v app_password='<strong-password>' -f deploy/postgres-init.sql
```

脚本不保存固定密码且可重复执行；再次执行会将 `lob_browser` 账号更新为本次传入的密码。启动前需通过本地 `.env` 或环境变量提供使用该密码的 `DATABASE_URL`。

```bash
uv run uvicorn lob_browser.web.api:app --reload --port 8090
```

接口启动时会自动创建 `browser_tasks`、`task_steps`、`task_approvals` 和 `task_events` 表。

## 许可证

本项目使用 [Apache License 2.0](./LICENSE) 开源。
