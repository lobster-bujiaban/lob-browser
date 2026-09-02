from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .db import connect, create_task, init, task

class CreateTask(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await connect()
    await init(app.state.db)
    yield
    await app.state.db.close()

app = FastAPI(title="LOB Browser API", version="0.1.0", lifespan=lifespan)

WEB_DIR = __import__("pathlib").Path(__file__).resolve().parents[3] / "web"

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
    return await task(request.app.state.db, task_id)

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: UUID, request: Request):
    value = await task(request.app.state.db, task_id)
    if value is None: raise HTTPException(404, "task not found")
    return value
