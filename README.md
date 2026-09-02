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
- [ ] 阶段 4：动态页面、标签页与复杂交互
- [ ] 阶段 5：可靠执行、恢复与人工审批
- [ ] 阶段 6：记忆、任务规划与多 Agent
- [ ] 阶段 7：评测、可观测与生产化
- [ ] 阶段 8：browser-use 源码映射与差异清单

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

## 项目边界

- `lob-browser` 关注网页任务执行，不重复实现 `lob-harness` 的通用 Agent 运行框架。
- 持久化状态机和复杂 Checkpoint 原理留给 `lob-graph`。
- Trace、Prompt 版本和系统化评测后续与 `lob-observe` 对接。
- 不绕过验证码、反爬、安全警告或网站权限边界。
- 不默认执行发布、删除、支付等有外部副作用的动作。

## 许可证

本项目使用 [Apache License 2.0](./LICENSE) 开源。
