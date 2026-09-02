"""Approval requests and audit records for high-risk browser actions."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field

from lob_browser.actions import Action


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class RiskAssessment(BaseModel):
    level: RiskLevel
    reason: str
    target_name: str = ""


class ApprovalRecord(BaseModel):
    request_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    task: str
    step: int
    action: Action
    url: str
    target_name: str = ""
    risk: RiskLevel
    reason: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None

    def decide(self, status: ApprovalStatus) -> "ApprovalRecord":
        return self.model_copy(update={"status": status, "decided_at": datetime.now(UTC)})
