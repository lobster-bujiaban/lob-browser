"""Atomic task checkpoints with a side-effect idempotency ledger."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from lob_browser.actions import ActionKind, ErrorKind
from lob_browser.approval import ApprovalRecord


class CheckpointStatus(StrEnum):
    RUNNING = "running"
    APPROVAL_REQUIRED = "approval_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SideEffectStatus(StrEnum):
    PENDING = "pending"
    COMPLETED = "completed"
    UNCERTAIN = "uncertain"


class CheckpointStep(BaseModel):
    step: int
    url: str
    title: str
    action_kind: ActionKind | None = None
    ok: bool | None = None
    error_kind: ErrorKind | None = None
    error: str | None = None
    retry_attempt: int = 0


class SideEffectRecord(BaseModel):
    key: str
    status: SideEffectStatus
    action_kind: ActionKind
    target_name: str
    url: str
    approval_request_id: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TaskCheckpoint(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex[:16])
    task: str
    status: CheckpointStatus = CheckpointStatus.RUNNING
    next_step: int = 1
    tokens_used: int = 0
    last_url: str = ""
    steps: list[CheckpointStep] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    side_effects: dict[str, SideEffectRecord] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CheckpointStore:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, run_id: str) -> Path:
        return self.directory / f"{run_id}.json"

    def load(self, run_id: str) -> TaskCheckpoint:
        return TaskCheckpoint.model_validate_json(self.path_for(run_id).read_text(encoding="utf-8"))

    def save(self, checkpoint: TaskCheckpoint) -> Path:
        checkpoint.updated_at = datetime.now(UTC)
        target = self.path_for(checkpoint.run_id)
        temporary = target.with_suffix(f".{uuid4().hex[:8]}.tmp")
        temporary.write_text(checkpoint.model_dump_json(indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, target)
        return target


def side_effect_key(task: str, url: str, action_kind: ActionKind, target_name: str) -> str:
    payload = json.dumps(
        {"task": task, "url": url, "action_kind": action_kind, "target_name": target_name},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:24]
