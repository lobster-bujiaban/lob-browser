"""Conservative risk classification for browser actions."""

from __future__ import annotations

from lob_browser.actions import Action, ActionKind
from lob_browser.approval.models import RiskAssessment, RiskLevel
from lob_browser.observation import Observation

_HIGH_RISK_TERMS = (
    "发布", "删除", "支付", "付款", "购买", "发送", "授权", "权限", "转账",
    "publish", "delete", "pay", "purchase", "send", "authorize", "permission", "transfer",
)


class ApprovalPolicy:
    def assess(self, task: str, action: Action, observation: Observation) -> RiskAssessment:
        element = observation.element(action.index) if action.index is not None else None
        target_name = element.name if element else ""
        if action.kind is ActionKind.CLICK:
            haystack = f"{task} {target_name}".lower()
            matched = next((term for term in _HIGH_RISK_TERMS if term in haystack), None)
            if matched:
                return RiskAssessment(
                    level=RiskLevel.HIGH,
                    reason=f"high-risk intent matched: {matched}",
                    target_name=target_name,
                )
        if action.kind in {ActionKind.UPLOAD, ActionKind.DIALOG}:
            return RiskAssessment(
                level=RiskLevel.MEDIUM,
                reason=f"controlled action: {action.kind}",
                target_name=target_name,
            )
        return RiskAssessment(level=RiskLevel.LOW, reason="no high-risk intent", target_name=target_name)
