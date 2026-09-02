from __future__ import annotations

import os
import json
from pathlib import Path
from uuid import UUID

import asyncpg

def _load_env() -> None:
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

_load_env()

SCHEMA = """
CREATE TABLE IF NOT EXISTS browser_tasks (
    id UUID PRIMARY KEY, title TEXT NOT NULL, prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', message TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ, result JSONB
);
CREATE TABLE IF NOT EXISTS task_steps (
    id BIGSERIAL PRIMARY KEY, task_id UUID NOT NULL REFERENCES browser_tasks(id) ON DELETE CASCADE,
    step_no INTEGER NOT NULL, status TEXT NOT NULL, label TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '', payload JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(task_id, step_no)
);
CREATE TABLE IF NOT EXISTS task_approvals (
    id UUID PRIMARY KEY, task_id UUID NOT NULL REFERENCES browser_tasks(id) ON DELETE CASCADE,
    step_no INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL,
    target_name TEXT NOT NULL DEFAULT '', decided_at TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS task_events (
    id BIGSERIAL PRIMARY KEY, task_id UUID NOT NULL REFERENCES browser_tasks(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL, payload JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS task_events_task_id_id_idx ON task_events(task_id, id);
"""

async def connect() -> asyncpg.Pool:
    return await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=5)

async def init(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)

async def create_task(pool: asyncpg.Pool, task_id: UUID, prompt: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO browser_tasks(id,title,prompt) VALUES($1,$2,$2)", task_id, prompt[:80])
        await conn.execute("INSERT INTO task_events(task_id,event_type,payload) VALUES($1,'task_created',$2::jsonb)", task_id, json.dumps({"prompt": prompt}, ensure_ascii=False))

async def task(pool: asyncpg.Pool, task_id: UUID) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM browser_tasks WHERE id=$1", task_id)
        if not row: return None
        steps = await conn.fetch("SELECT * FROM task_steps WHERE task_id=$1 ORDER BY step_no", task_id)
        events = await conn.fetch("SELECT * FROM task_events WHERE task_id=$1 ORDER BY id", task_id)
        return {**dict(row), "steps": [dict(x) for x in steps], "events": [dict(x) for x in events]}
