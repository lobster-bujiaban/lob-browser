"""Observe → Decide → Validate → Act.

Mapped from browser-use 0.13.7 Agent.step; no EventBus, one structured action per step.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from lob_browser.actions import run_action
from lob_browser.agent.models import AgentResult, Decision, StepRecord, StopReason
from lob_browser.agent.validate import InvalidDecision, fingerprint, validate_decision
from lob_browser.browser import BrowserSession
from lob_browser.observation import Observation, observe

Decider = Callable[[str, Observation, list[StepRecord]], Awaitable[Decision]]


async def run_task(
    session: BrowserSession,
    task: str,
    decider: Decider,
    *,
    max_steps: int = 8,
    max_tokens: int = 50_000,
) -> AgentResult:
    steps: list[StepRecord] = []
    tokens_used = 0
    repeats = 0

    for step_no in range(1, max_steps + 1):
        observation = await observe(session)
        tokens_used += observation.token_estimate
        if tokens_used > max_tokens:
            return AgentResult(
                ok=False,
                stop_reason=StopReason.TOKEN_BUDGET,
                message=f"token budget {max_tokens} exceeded",
                steps=steps,
                tokens_used=tokens_used,
            )

        try:
            decision = await decider(task, observation, steps)
            decision = validate_decision(decision, observation)
        except InvalidDecision as exc:
            steps.append(
                StepRecord(
                    step=step_no,
                    observation_id=observation.observation_id,
                    url=observation.url,
                    title=observation.title,
                    error=str(exc),
                    token_estimate=observation.token_estimate,
                )
            )
            continue
        except Exception as exc:
            steps.append(
                StepRecord(
                    step=step_no,
                    observation_id=observation.observation_id,
                    url=observation.url,
                    title=observation.title,
                    error=f"decide failed: {type(exc).__name__}: {exc}",
                    token_estimate=observation.token_estimate,
                )
            )
            continue

        if decision.done:
            steps.append(
                StepRecord(
                    step=step_no,
                    observation_id=observation.observation_id,
                    url=observation.url,
                    title=observation.title,
                    thought=decision.thought,
                    error=None if decision.success else decision.message or "done with success=false",
                    token_estimate=observation.token_estimate,
                )
            )
            return AgentResult(
                ok=decision.success,
                stop_reason=StopReason.DONE if decision.success else StopReason.FAILED,
                message=decision.message or decision.thought,
                steps=steps,
                tokens_used=tokens_used,
            )

        action = decision.action
        assert action is not None
        if _is_repeat_failure(action, steps):
            repeats += 1
            steps.append(
                StepRecord(
                    step=step_no,
                    observation_id=observation.observation_id,
                    url=observation.url,
                    title=observation.title,
                    thought=decision.thought,
                    action=action,
                    error="skipped repeated failed action",
                    token_estimate=observation.token_estimate,
                )
            )
            if repeats >= 3:
                return AgentResult(
                    ok=False,
                    stop_reason=StopReason.REPEATED_FAILURE,
                    message="same failed action repeated",
                    steps=steps,
                    tokens_used=tokens_used,
                )
            continue

        result = await run_action(session, action)
        steps.append(
            StepRecord(
                step=step_no,
                observation_id=observation.observation_id,
                url=observation.url,
                title=observation.title,
                thought=decision.thought,
                action=action,
                result=result,
                error=None if result.ok else result.error,
                token_estimate=observation.token_estimate,
            )
        )

    return AgentResult(
        ok=False,
        stop_reason=StopReason.MAX_STEPS,
        message=f"stopped after {max_steps} steps",
        steps=steps,
        tokens_used=tokens_used,
    )


def _is_repeat_failure(action, steps: list[StepRecord]) -> bool:
    if not steps:
        return False
    last = steps[-1]
    if last.action is None or last.error is None:
        return False
    return fingerprint(last.action) == fingerprint(action)
