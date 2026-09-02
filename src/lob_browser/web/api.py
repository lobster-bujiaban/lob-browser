from __future__ import annotations

from contextlib import asynccontextmanager
import asyncio
import os
from typing import Literal
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lob_browser.agent import run_task
from lob_browser.agent.crawl import GenericCrawler
from lob_browser.browser import BrowserSession, SessionConfig
from lob_browser.providers.openai import OpenAICompatibleDecider, plan_crawl
from .db import connect, create_empty_task, create_task, delete_task, delete_tasks, init, prepare_task, rename_task, save_collected_items, save_steps, set_task_status, task, tasks

class CreateTask(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    mode: Literal["auto", "agent", "crawl"] = "auto"

class TaskTitle(BaseModel):
    title: str = Field(min_length=1, max_length=80)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await connect()
    await init(app.state.db)
    yield
    await app.state.db.close()

app = FastAPI(title="LOB Browser API", version="0.1.0", lifespan=lifespan)

WEB_DIR = __import__("pathlib").Path(__file__).resolve().parents[3] / "web"
app.mount("/src", StaticFiles(directory=WEB_DIR / "src"), name="web-src")

@app.get("/", include_in_schema=False)
async def web_home():
    return FileResponse(WEB_DIR / "index.html")

@app.get("/styles.css", include_in_schema=False)
async def web_styles():
    return FileResponse(WEB_DIR / "styles.css", media_type="text/css")

@app.get("/app.js", include_in_schema=False)
async def web_script():
    return FileResponse(WEB_DIR / "app.js", media_type="application/javascript")

@app.get("/api/health")
async def health(request: Request):
    async with request.app.state.db.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True, "database": "postgresql"}

@app.post("/api/tasks", status_code=201)
async def new_task(body: CreateTask, request: Request):
    task_id = uuid4()
    await create_task(request.app.state.db, task_id, body.prompt)
    asyncio.create_task(_execute_task(request.app.state.db, task_id, body.prompt, body.mode))
    return await task(request.app.state.db, task_id)

@app.post("/api/tasks/empty", status_code=201)
async def new_empty_task(body: TaskTitle, request: Request):
    task_id = uuid4()
    await create_empty_task(request.app.state.db, task_id, body.title.strip())
    return await task(request.app.state.db, task_id)

@app.post("/api/tasks/{task_id}/run")
async def run_existing_task(task_id: UUID, body: CreateTask, request: Request):
    if not await prepare_task(request.app.state.db, task_id, body.prompt):
        raise HTTPException(404, "task not found")
    asyncio.create_task(_execute_task(request.app.state.db, task_id, body.prompt, body.mode))
    return await task(request.app.state.db, task_id)

@app.get("/api/tasks")
async def list_tasks(request: Request):
    return await tasks(request.app.state.db)

@app.delete("/api/tasks")
async def clear_tasks(request: Request):
    return {"deleted": await delete_tasks(request.app.state.db)}

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: UUID, request: Request):
    value = await task(request.app.state.db, task_id)
    if value is None: raise HTTPException(404, "task not found")
    return value

@app.delete("/api/tasks/{task_id}", status_code=204)
async def remove_task(task_id: UUID, request: Request):
    if not await delete_task(request.app.state.db, task_id):
        raise HTTPException(404, "task not found")

@app.patch("/api/tasks/{task_id}")
async def update_task_title(task_id: UUID, body: TaskTitle, request: Request):
    if not await rename_task(request.app.state.db, task_id, body.title.strip()):
        raise HTTPException(404, "task not found")
    return await task(request.app.state.db, task_id)

async def _execute_task(pool, task_id: UUID, prompt: str, mode: str = "auto") -> None:
    plan = await plan_crawl(prompt) if mode in {"auto", "crawl"} else None
    if plan is None and not os.environ.get("OPENAI_API_KEY"):
        await set_task_status(pool, task_id, "failed", "模型未配置：请在 .env 设置 OPENAI_API_KEY、OPENAI_MODEL 和 OPENAI_BASE_URL")
        return
    await set_task_status(pool, task_id, "running", "Agent 正在启动浏览器")
    session = BrowserSession(SessionConfig(headless=True))
    try:
        decider = GenericCrawler(plan) if plan is not None else OpenAICompatibleDecider()
        await session.start()
        async def persist_steps(steps):
            await save_steps(pool, task_id, _step_rows(steps))
        max_steps = min(52, plan.max_pages + 2) if plan is not None else 12
        result = await run_task(session, prompt, decider, max_steps=max_steps, trace_path=f"artifacts/{task_id}.jsonl", on_steps=persist_steps)
        rows = _step_rows(result.steps)
        await save_steps(pool, task_id, rows)
        await save_collected_items(pool, task_id, [item.model_dump() for item in result.collected_items])
        await set_task_status(pool, task_id, "completed" if result.ok else "failed", result.message, result.model_dump(mode="json"))
    except Exception as exc:
        await set_task_status(pool, task_id, "failed", f"执行失败：{type(exc).__name__}: {exc}")
    finally:
        await session.close()

def _step_rows(steps) -> list[dict]:
    return [{"step_no": step.step, "status": "succeeded" if step.result and step.result.ok else "failed" if step.error or (step.result and not step.result.ok) else "observed", "label": step.action.kind.value if step.action else "完成判断", "detail": step.error or (step.result.message if step.result else step.thought), "payload": step.model_dump(mode="json")} for step in steps]
