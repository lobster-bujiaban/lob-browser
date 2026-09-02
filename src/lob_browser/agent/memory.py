"""Bounded task memory for long-running browser tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskMemory(BaseModel):
    goal: str
    completed: list[str] = Field(default_factory=list)
    failed_attempts: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)
    facts: dict[str, str] = Field(default_factory=dict)
    max_items: int = 20

    def add_completed(self, item: str) -> None:
        self._append_unique(self.completed, item)
        if item in self.pending:
            self.pending.remove(item)

    def add_failed(self, item: str) -> None:
        self._append_unique(self.failed_attempts, item)

    def add_pending(self, item: str) -> None:
        self._append_unique(self.pending, item)

    def context(self) -> str:
        return "\n".join(
            [f"goal: {self.goal}", f"completed: {', '.join(self.completed)}", f"pending: {', '.join(self.pending)}", f"failed: {', '.join(self.failed_attempts)}"]
        )

    def _append_unique(self, bucket: list[str], value: str) -> None:
        if value not in bucket:
            bucket.append(value)
        del bucket[:-self.max_items]


class Planner:
    def plan(self, goal: str, steps: list[str]) -> TaskMemory:
        memory = TaskMemory(goal=goal)
        for step in steps:
            memory.add_pending(step)
        return memory


class Executor:
    def mark(self, memory: TaskMemory, step: str, *, ok: bool) -> None:
        if ok:
            memory.add_completed(step)
        else:
            memory.add_failed(step)
