"""Validate a model decision against the current observation."""

from __future__ import annotations

from lob_browser.actions import Action
from lob_browser.agent.models import Decision
from lob_browser.observation import Observation


class InvalidDecision(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_decision(decision: Decision, observation: Observation) -> Decision:
    if decision.done:
        return decision
    action = decision.action
    if action is None:
        raise InvalidDecision("decision needs an action or done=true")
    if action.index is not None:
        if action.observation_id and action.observation_id != observation.observation_id:
            raise InvalidDecision("observation_id does not match current page observation")
        if observation.element(action.index) is None:
            raise InvalidDecision(f"index {action.index} is not in the current observation")
        action = action.model_copy(update={"observation_id": observation.observation_id})
        return decision.model_copy(update={"action": action})
    return decision


def fingerprint(action: Action) -> tuple[object, ...]:
    return (
        action.kind,
        action.index,
        action.selector,
        action.url,
        action.text,
        action.value,
        action.tab_id,
        action.accept,
        action.prompt_text,
        action.wait_condition,
        action.load_state,
        action.file_path,
        action.until_text,
        action.until_selector,
        action.max_scrolls,
    )
