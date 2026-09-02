"""Observe → Decide → Validate → Act.

Mapped from browser-use 0.13.7 Agent.step; no EventBus, one structured action per step.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from lob_browser.actions import run_action
from lob_browser.approval import ApprovalHandler, ApprovalPolicy, ApprovalRecord, ApprovalStatus, RiskLevel
from lob_browser.agent.models import AgentResult, Decision, StepRecord, StopReason
from lob_browser.agent.validate import InvalidDecision, fingerprint, validate_decision
from lob_browser.agent.trace import TraceWriter
from lob_browser.agent.retry import RetryPolicy, recovery_strategy
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
    trace_path: str | Path | None = None,
    retry_policy: RetryPolicy | None = None,
    approval_policy: ApprovalPolicy | None = None,
    approval_handler: ApprovalHandler | None = None,
) -> AgentResult:
    steps: list[StepRecord] = []
    approvals: list[ApprovalRecord] = []
    tokens_used = 0
    repeats = 0
    policy = retry_policy or RetryPolicy()
    risk_policy = approval_policy or ApprovalPolicy()
    retry_attempt = 0
    retry_of_step: int | None = None
    pending_recovery: str | None = None
    trace = TraceWriter(trace_path) if trace_path else None
    if trace:
        trace.write(
            "task_started",
            task=task,
            max_steps=max_steps,
            max_tokens=max_tokens,
            retry_policy=policy,
        )

    for step_no in range(1, max_steps + 1):
        observation = await observe(session)
        if trace:
            trace.write("observation", step=step_no, observation=observation)
        tokens_used += observation.token_estimate
        if tokens_used > max_tokens:
            return _finish(trace, approvals, AgentResult(
                ok=False,
                stop_reason=StopReason.TOKEN_BUDGET,
                message=f"token budget {max_tokens} exceeded",
                steps=steps,
                tokens_used=tokens_used,
            ))

        try:
            decision = await decider(task, observation, steps)
            decision = validate_decision(decision, observation)
            if trace:
                trace.write("decision", step=step_no, decision=decision)
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
            return _finish(trace, approvals, AgentResult(
                ok=decision.success,
                stop_reason=StopReason.DONE if decision.success else StopReason.FAILED,
                message=decision.message or decision.thought,
                steps=steps,
                tokens_used=tokens_used,
            ))

        action = decision.action
        assert action is not None
        if retry_attempt == 0 and _is_repeat_failure(action, steps):
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
                    retry_attempt=retry_attempt,
                    retry_of_step=retry_of_step,
                )
            )
            if repeats >= 3:
                return _finish(trace, approvals, AgentResult(
                    ok=False,
                    stop_reason=StopReason.REPEATED_FAILURE,
                    message="same failed action repeated",
                    steps=steps,
                    tokens_used=tokens_used,
                ))
            continue

        assessment = risk_policy.assess(task, action, observation)
        approval: ApprovalRecord | None = None
        if assessment.level is RiskLevel.HIGH:
            approval = ApprovalRecord(
                task=task,
                step=step_no,
                action=action,
                url=observation.url,
                target_name=assessment.target_name,
                risk=assessment.level,
                reason=assessment.reason,
            )
            if trace:
                trace.write("approval_requested", approval=approval)
            if approval_handler is None:
                approvals.append(approval)
                steps.append(
                    StepRecord(
                        step=step_no,
                        observation_id=observation.observation_id,
                        url=observation.url,
                        title=observation.title,
                        thought=decision.thought,
                        action=action,
                        error="high-risk action requires approval",
                        token_estimate=observation.token_estimate,
                        approval_request_id=approval.request_id,
                        approval_status=approval.status,
                        risk_level=approval.risk,
                        approval_reason=approval.reason,
                    )
                )
                return _finish(trace, approvals, AgentResult(
                    ok=False,
                    stop_reason=StopReason.APPROVAL_REQUIRED,
                    message=f"approval required: {approval.request_id}",
                    steps=steps,
                    tokens_used=tokens_used,
                ))
            try:
                status = await approval_handler(approval)
            except Exception:
                status = ApprovalStatus.CANCELLED
            approval = approval.decide(status)
            approvals.append(approval)
            if trace:
                trace.write("approval_decided", approval=approval)
            if status is not ApprovalStatus.APPROVED:
                steps.append(
                    StepRecord(
                        step=step_no,
                        observation_id=observation.observation_id,
                        url=observation.url,
                        title=observation.title,
                        thought=decision.thought,
                        action=action,
                        error=f"approval {status}",
                        token_estimate=observation.token_estimate,
                        approval_request_id=approval.request_id,
                        approval_status=approval.status,
                        risk_level=approval.risk,
                        approval_reason=approval.reason,
                    )
                )
                stop_reason = (
                    StopReason.APPROVAL_REJECTED
                    if status is ApprovalStatus.REJECTED
                    else StopReason.CANCELLED
                )
                return _finish(trace, approvals, AgentResult(
                    ok=False,
                    stop_reason=stop_reason,
                    message=f"approval {status}: {approval.request_id}",
                    steps=steps,
                    tokens_used=tokens_used,
                ))

        result = await run_action(session, action)
        strategy = recovery_strategy(action, result) if not result.ok else None
        if trace:
            trace.write(
                "action_result",
                step=step_no,
                result=result,
                retry_attempt=retry_attempt,
                retry_of_step=retry_of_step,
                approval=approval,
            )
        record = StepRecord(
            step=step_no,
            observation_id=observation.observation_id,
            url=observation.url,
            title=observation.title,
            thought=decision.thought,
            action=action,
            result=result,
            error=None if result.ok else result.error,
            token_estimate=observation.token_estimate,
            retry_attempt=retry_attempt,
            retry_of_step=retry_of_step,
            recovery_strategy=pending_recovery if retry_attempt else strategy,
            approval_request_id=approval.request_id if approval else None,
            approval_status=approval.status if approval else None,
            risk_level=assessment.level,
            approval_reason=assessment.reason if approval else None,
        )
        steps.append(record)

        if not result.ok and strategy:
            if retry_attempt >= policy.max_retries:
                return _finish(trace, approvals, AgentResult(
                    ok=False,
                    stop_reason=StopReason.RETRY_EXHAUSTED,
                    message=f"retry limit {policy.max_retries} exhausted: {result.error}",
                    steps=steps,
                    tokens_used=tokens_used,
                ))
            next_attempt = retry_attempt + 1
            retry_of_step = retry_of_step or step_no
            pending_recovery = strategy
            backoff_ms = policy.backoff_ms(next_attempt)
            if trace:
                trace.write(
                    "retry_scheduled",
                    step=step_no,
                    retry_of_step=retry_of_step,
                    retry_attempt=next_attempt,
                    strategy=strategy,
                    backoff_ms=backoff_ms,
                    error_kind=result.error_kind,
                    error=result.error,
                )
            retry_attempt = next_attempt
            await asyncio.sleep(backoff_ms / 1000)
            continue

        retry_attempt = 0
        retry_of_step = None
        pending_recovery = None

    return _finish(trace, approvals, AgentResult(
        ok=False,
        stop_reason=StopReason.MAX_STEPS,
        message=f"stopped after {max_steps} steps",
        steps=steps,
        tokens_used=tokens_used,
    ))


def _finish(
    trace: TraceWriter | None,
    approvals: list[ApprovalRecord],
    result: AgentResult,
) -> AgentResult:
    result = result.model_copy(update={"approvals": approvals})
    if trace:
        trace.write("task_finished", result=result)
    return result


def _is_repeat_failure(action, steps: list[StepRecord]) -> bool:
    if not steps:
        return False
    last = steps[-1]
    if last.action is None or last.error is None:
        return False
    return fingerprint(last.action) == fingerprint(action)
