"""Agent loop state: decisions, steps, and stop reasons.

Mapped from browser-use 0.13.7 AgentOutput / ActionResult.is_done.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from lob_browser.actions import Action, ActionResult


class StopReason(StrEnum):
    DONE = "done"
    FAILED = "failed"
    MAX_STEPS = "max_steps"
    TOKEN_BUDGET = "token_budget"
    REPEATED_FAILURE = "repeated_failure"
    RETRY_EXHAUSTED = "retry_exhausted"


class Decision(BaseModel):
    thought: str = ""
    done: bool = False
    success: bool = False
    message: str = ""
    action: Action | None = None


class StepRecord(BaseModel):
    step: int
    observation_id: str
    url: str
    title: str
    thought: str = ""
    action: Action | None = None
    result: ActionResult | None = None
    error: str | None = None
    token_estimate: int = 0
    retry_attempt: int = 0
    retry_of_step: int | None = None
    recovery_strategy: str | None = None


class AgentResult(BaseModel):
    ok: bool
    stop_reason: StopReason
    message: str
    steps: list[StepRecord] = Field(default_factory=list)
    tokens_used: int = 0
