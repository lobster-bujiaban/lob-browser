English | [中文](README.cn.md)

# LOB Browser

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](./LICENSE)

**Status: research** — Playwright browser agent mapped from browser-use 0.13.7 (`src/lob_browser/agent/loop.py`). Local fixtures, not a hosted product.

## What

Observe → decide → validate → one structured action per step, with JSONL traces, retries, approval, checkpoints, and optional crawl / eval helpers.

## Run in 3 commands

Python 3.12+ and `uv`. Smoke uses **scripted** decisions (`LocalScriptedDecider`), not an LLM.

```bash
uv sync
uv run python -m playwright install chromium
uv run python -m lob_browser.agent.local_smoke
```

Writes `artifacts/local-smoke.jsonl`. Tasks in `local_smoke.py`: local form, dynamic list, multi-tab, plus checks for stale indexes, dialogs, iframe, shadow DOM, download, upload, wait, scroll.

## Architecture

```text
run_task (agent/loop.py)
  → observe (observation/collect.py)
  → Decider  (LLM | LocalScriptedDecider | GenericCrawler)
  → validate_decision (agent/validate.py)
  → ApprovalPolicy / ApprovalHandler
  → run_action (actions/executor.py)
  → TraceWriter + optional CheckpointStore (runtime/checkpoint.py)
```

Defaults in `run_task`: `max_steps=8`, `max_tokens=50_000`.

### Actions (`actions/models.py` `ActionKind`)

`navigate`, `back`, `reload`, `click`, `type`, `select`, `scroll`, `wait`, `new_tab`, `switch_tab`, `close_tab`, `dialog`, `upload`.

Wait conditions: `duration`, `selector_visible`, `text`, `url`, `load_state`. Error kinds include `stale_element`, `dialog_unhandled`, `upload_not_allowed`, `scroll_limit`.

### Web API (not a static demo)

`src/lob_browser/web/api.py` is FastAPI: serves `web/index.html` **and** runs tasks.

```bash
# DATABASE_URL required (asyncpg). Create the role with deploy/postgres-init.sql
uv run uvicorn lob_browser.web.api:app --reload --port 8090
```

`POST /api/tasks` body `mode`: `auto` | `agent` | `crawl`. Crawl uses `GenericCrawler` (`agent/crawl.py`): `max_depth≤3`, `max_pages≤50`. LLM path: `providers/openai.py` `OpenAICompatibleDecider`. Cancel: `POST /api/tasks/{id}/cancel`. Health checks PostgreSQL.

`python3 -m http.server` only serves static files; it does **not** execute agents.

### Eval

`evaluation/runner.py` `evaluate_suite` records ok / steps / tokens / retries / elapsed. No separate CLI entry; import the runner.

## Bounds in code

- Loop comment: no EventBus; **one structured action per step**.
- Upload only under `SessionConfig.upload_roots` after realpath checks.
- Captcha / anti-bot bypass is not implemented; do not add it.
- Checkpoints skip re-run if status is already `COMPLETED`.

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Contact

[chishishuan@gmail.com](mailto:chishishuan@gmail.com) · [GitHub Issues](https://github.com/lobster-bujiaban/lob-browser/issues)
