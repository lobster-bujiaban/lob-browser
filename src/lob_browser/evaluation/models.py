"""Fixed evaluation cases and aggregate metrics."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EvaluationCase(BaseModel):
    name: str
    task: str
    expected_message: str | None = None


class EvaluationResult(BaseModel):
    case: str
    ok: bool
    message: str
    steps: int
    tokens_used: int
    retries: int = 0
    elapsed_ms: float = 0


class Metrics(BaseModel):
    total: int = 0
    succeeded: int = 0
    success_rate: float = 0
    average_steps: float = 0
    average_tokens: float = 0
    total_retries: int = 0

    @classmethod
    def from_results(cls, results: list[EvaluationResult]) -> "Metrics":
        total = len(results)
        return cls(
            total=total,
            succeeded=sum(item.ok for item in results),
            success_rate=sum(item.ok for item in results) / total if total else 0,
            average_steps=sum(item.steps for item in results) / total if total else 0,
            average_tokens=sum(item.tokens_used for item in results) / total if total else 0,
            total_retries=sum(item.retries for item in results),
        )


class EvaluationSuite(BaseModel):
    name: str
    cases: list[EvaluationCase] = Field(default_factory=list)
