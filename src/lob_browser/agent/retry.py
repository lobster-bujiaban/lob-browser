"""Bounded retry policy for browser actions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from lob_browser.actions import Action, ActionKind, ActionResult, ErrorKind


class RetryPolicy(BaseModel):
    max_retries: int = Field(default=2, ge=0)
    base_backoff_ms: float = Field(default=100, ge=0)
    max_backoff_ms: float = Field(default=1_000, ge=0)

    def backoff_ms(self, attempt: int) -> float:
        return min(self.base_backoff_ms * (2 ** max(attempt - 1, 0)), self.max_backoff_ms)


_SAFE_TIMEOUT_ACTIONS = {
    ActionKind.NAVIGATE,
    ActionKind.RELOAD,
    ActionKind.WAIT,
    ActionKind.SCROLL,
    ActionKind.SWITCH_TAB,
}


def recovery_strategy(action: Action, result: ActionResult) -> str | None:
    if result.error_kind in {ErrorKind.STALE_ELEMENT, ErrorKind.ELEMENT_NOT_FOUND}:
        return "reobserve_and_retry"
    if result.error_kind is ErrorKind.TIMEOUT and action.kind in _SAFE_TIMEOUT_ACTIONS:
        return "backoff_reobserve_and_retry"
    return None
