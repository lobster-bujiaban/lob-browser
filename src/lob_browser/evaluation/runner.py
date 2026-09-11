from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from lob_browser.agent.models import AgentResult
from lob_browser.evaluation.models import EvaluationCase, EvaluationResult, EvaluationSuite, Metrics


async def evaluate_suite(
    suite: EvaluationSuite,
    runner: Callable[[EvaluationCase], Awaitable[AgentResult]],
) -> tuple[list[EvaluationResult], Metrics]:
    results = []
    for case in suite.cases:
        started = time.perf_counter()
        result = await runner(case)
        results.append(
            EvaluationResult(
                case=case.name,
                ok=result.ok and (case.expected_message is None or case.expected_message in result.message),
                message=result.message,
                steps=len(result.steps),
                tokens_used=result.tokens_used,
                retries=sum(step.retry_attempt for step in result.steps),
                elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
            )
        )
    return results, Metrics.from_results(results)
