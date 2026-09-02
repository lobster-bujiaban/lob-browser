"""Agent loop state: decisions, steps, and stop reasons.

Mapped from browser-use 0.13.7 AgentOutput / ActionResult.is_done.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from lob_browser.actions import Action, ActionResult
from lob_browser.approval import ApprovalRecord, ApprovalStatus, RiskLevel


class StopReason(StrEnum):
    DONE = "done"
    FAILED = "failed"
    MAX_STEPS = "max_steps"
    TOKEN_BUDGET = "token_budget"
    REPEATED_FAILURE = "repeated_failure"
    RETRY_EXHAUSTED = "retry_exhausted"
    APPROVAL_REQUIRED = "approval_required"
    APPROVAL_REJECTED = "approval_rejected"
    CANCELLED = "cancelled"
    SIDE_EFFECT_BLOCKED = "side_effect_blocked"
    SIDE_EFFECT_UNCERTAIN = "side_effect_uncertain"


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
    approval_request_id: str | None = None
    approval_status: ApprovalStatus | None = None
    risk_level: RiskLevel | None = None
    approval_reason: str | None = None


class AgentResult(BaseModel):
    ok: bool
    stop_reason: StopReason
    message: str
    steps: list[StepRecord] = Field(default_factory=list)
    tokens_used: int = 0
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    run_id: str | None = None
    checkpoint_path: str | None = None
