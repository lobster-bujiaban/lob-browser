"""Approval handler protocol and deterministic handler for integrations/tests."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from lob_browser.approval.models import ApprovalRecord, ApprovalStatus

ApprovalHandler = Callable[[ApprovalRecord], Awaitable[ApprovalStatus]]


class StaticApprovalHandler:
    def __init__(self, status: ApprovalStatus) -> None:
        if status is ApprovalStatus.PENDING:
            raise ValueError("handler must return a terminal approval status")
        self.status = status

    async def __call__(self, request: ApprovalRecord) -> ApprovalStatus:
        return self.status
