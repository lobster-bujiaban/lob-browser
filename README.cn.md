[English](README.md) | 中文

# LOB Browser

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

**状态：研究** — Playwright 浏览器 Agent，对照 browser-use 0.13.7（`src/lob_browser/agent/loop.py`）。本地 fixture，不是托管产品。

## What

观察 → 决策 → 校验 → 每步一个结构化动作；带 JSONL Trace、重试、审批、checkpoint，以及可选的爬取 / 评测。

## Run in 3 commands

Python 3.12+ 和 `uv`。冒烟用 **脚本决策**（`LocalScriptedDecider`），不调 LLM。

```bash
uv sync
uv run python -m playwright install chromium
uv run python -m lob_browser.agent.local_smoke
```

写出 `artifacts/local-smoke.jsonl`。`local_smoke.py` 覆盖：本地表单、动态列表、多标签，以及失效索引、弹窗、iframe、Shadow DOM、下载、上传、等待、滚动。

## Architecture

```text
run_task (agent/loop.py)
  → observe (observation/collect.py)
  → Decider  (LLM | LocalScriptedDecider | GenericCrawler)
  → validate_decision (agent/validate.py)
  → ApprovalPolicy / ApprovalHandler
  → run_action (actions/executor.py)
  → TraceWriter + 可选 CheckpointStore (runtime/checkpoint.py)
```

`run_task` 默认：`max_steps=8`，`max_tokens=50_000`。

### 动作（`actions/models.py` 的 `ActionKind`）

`navigate`、`back`、`reload`、`click`、`type`、`select`、`scroll`、`wait`、`new_tab`、`switch_tab`、`close_tab`、`dialog`、`upload`。

等待条件：`duration`、`selector_visible`、`text`、`url`、`load_state`。错误类型含 `stale_element`、`dialog_unhandled`、`upload_not_allowed`、`scroll_limit`。

### Web API（不是静态演示页）

`src/lob_browser/web/api.py` 是 FastAPI：托管 `web/index.html`，**同时跑任务**。

```bash
# 需要 DATABASE_URL（asyncpg）。账号用 deploy/postgres-init.sql 创建
uv run uvicorn lob_browser.web.api:app --reload --port 8090
```

`POST /api/tasks` 的 `mode`：`auto` | `agent` | `crawl`。爬取走 `GenericCrawler`（`agent/crawl.py`）：`max_depth≤3`，`max_pages≤50`。LLM 路径：`providers/openai.py` 的 `OpenAICompatibleDecider`。取消：`POST /api/tasks/{id}/cancel`。健康检查打 PostgreSQL。

`python3 -m http.server` 只提供静态文件，**不会执行 Agent**。

### 评测

`evaluation/runner.py` 的 `evaluate_suite` 记录 ok / steps / tokens / retries / elapsed。没有单独 CLI，需要 import。

## 代码里的边界

- loop 注释：没有 EventBus；**每步一个结构化动作**。
- 上传只允许 `SessionConfig.upload_roots` 内经 realpath 校验的文件。
- 没有验证码 / 反爬绕过，也不要加。
- checkpoint 状态已是 `COMPLETED` 则跳过重跑。

## 许可证

Apache License 2.0，见 [LICENSE](LICENSE)。

## 联系

[chishishuan@gmail.com](mailto:chishishuan@gmail.com) · [GitHub Issues](https://github.com/lobster-bujiaban/lob-browser/issues)
