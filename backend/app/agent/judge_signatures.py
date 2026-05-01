"""Gate 6 judge helpers for Dev D without eval-runner coupling."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.guardrails.policies import DEFAULT_POLICY, compact_text
from app.schemas.api import ExplainResponse
from app.schemas.domain import Evidence


class JudgeModel(BaseModel):
    """Base model for structured judge helper payloads."""

    model_config = ConfigDict(extra="forbid")


class JudgeSupportStatus(JudgeModel):
    """Callable status for the Dev C judge path."""

    callable: bool
    backend: str
    deterministic_fallback: bool
    skip_reason: str | None = None


class JudgeInputPayload(JudgeModel):
    """Safe judge input payload without prompts, secrets, or chain-of-thought."""

    expected: str
    prediction: str
    evidence: list[dict[str, str | float]]


class JudgeResult(JudgeModel):
    """Structured judge result usable by Dev D metrics."""

    status: JudgeSupportStatus
    score: float = Field(ge=0.0, le=1.0)
    error_labels: list[str] = Field(default_factory=list)


def judge_support_status(runner: Any | None = None) -> JudgeSupportStatus:
    """Return whether the current runner exposes a callable judge helper."""

    if runner is None:
        return JudgeSupportStatus(
            callable=True,
            backend="deterministic_fallback",
            deterministic_fallback=True,
            skip_reason="no_runner_supplied_using_deterministic_overlap_judge",
        )
    if callable(getattr(runner, "judge_evaluation_case", None)):
        deterministic = getattr(runner, "adapter_mode", "deterministic_dev") != "none"
        return JudgeSupportStatus(
            callable=True,
            backend="runner_judge",
            deterministic_fallback=deterministic,
            skip_reason="runner_is_deterministic_fallback" if deterministic else None,
        )
    return JudgeSupportStatus(
        callable=False,
        backend="unavailable",
        deterministic_fallback=True,
        skip_reason="runner_does_not_expose_judge_evaluation_case",
    )


def build_judge_input_payload(
    *,
    expected_points: Sequence[str],
    response: ExplainResponse,
    evidence: Sequence[Evidence],
) -> JudgeInputPayload:
    """Build safe judge inputs from public output and evidence identifiers."""

    return JudgeInputPayload(
        expected="\n".join(compact_text(point, limit=240) for point in expected_points),
        prediction="\n".join(
            _safe_judge_text(bullet.text, limit=420) for bullet in response.bullets
        ),
        evidence=[
            {
                "id": item.id,
                "document_id": item.document_id,
                "source_id": item.source_id,
                "score": _finite_score(item.score),
                "text": _safe_judge_text(item.text, limit=420),
            }
            for item in evidence
        ],
    )


def judge_response_quality(
    *,
    expected_points: Sequence[str],
    response: ExplainResponse,
    evidence: Sequence[Evidence],
    runner: Any | None = None,
) -> JudgeResult:
    """Run the runner judge when callable, otherwise use deterministic overlap."""

    payload = build_judge_input_payload(
        expected_points=expected_points,
        response=response,
        evidence=evidence,
    )
    status = judge_support_status(runner)
    if not status.callable:
        fallback = _deterministic_judge(payload)
        return JudgeResult(status=status, score=fallback.score, error_labels=fallback.error_labels)
    if runner is None:
        fallback = _deterministic_judge(payload)
        return JudgeResult(status=status, score=fallback.score, error_labels=fallback.error_labels)
    try:
        result = runner.judge_evaluation_case(
            payload.expected,
            payload.prediction,
            _evidence_from_payload(payload),
        )
    except Exception as exc:
        fallback = _deterministic_judge(payload)
        return JudgeResult(
            status=JudgeSupportStatus(
                callable=True,
                backend="deterministic_fallback",
                deterministic_fallback=True,
                skip_reason=f"runner_judge_failed:{exc.__class__.__name__}",
            ),
            score=fallback.score,
            error_labels=_dedupe(["judge_runtime_error", *fallback.error_labels]),
        )
    return JudgeResult(
        status=status,
        score=_score(result),
        error_labels=_labels(result),
    )


def _deterministic_judge(payload: JudgeInputPayload) -> JudgeResult:
    expected_terms = {
        token.strip(".,:;!?").lower()
        for token in payload.expected.split()
        if len(token.strip(".,:;!?")) > 3
    }
    prediction = payload.prediction.lower()
    matched = sum(1 for term in expected_terms if term in prediction)
    score = matched / len(expected_terms) if expected_terms else 1.0
    labels = [] if score >= 0.5 else ["low_expected_point_overlap"]
    return JudgeResult(
        status=JudgeSupportStatus(
            callable=True,
            backend="deterministic_fallback",
            deterministic_fallback=True,
            skip_reason="deterministic_overlap_judge",
        ),
        score=round(score, 3),
        error_labels=labels,
    )


def _score(result: Any) -> float:
    if isinstance(result, dict):
        raw_score = result.get("score", 0.0)
    else:
        raw_score = getattr(result, "score", 0.0)
    try:
        score = float(raw_score)
    except (TypeError, ValueError):
        return 0.0
    if not isfinite(score):
        return 0.0
    return max(0.0, min(1.0, score))


def _finite_score(value: float) -> float:
    score = float(value)
    if not isfinite(score):
        return 0.0
    return round(score, 4)


def _safe_judge_text(text: str, *, limit: int) -> str:
    if DEFAULT_POLICY.forbidden_output_hits(text):
        return "Untrusted evidence contained instruction-like or credential-seeking text."
    return compact_text(text, limit=limit)


def _evidence_from_payload(payload: JudgeInputPayload) -> list[Evidence]:
    return [
        Evidence.model_construct(
            id=str(item["id"]),
            document_id=str(item.get("document_id", item["id"])),
            text=str(item["text"]),
            score=float(item["score"]),
            source_id=str(item["source_id"]),
        )
        for item in payload.evidence
    ]


def _labels(result: Any) -> list[str]:
    if isinstance(result, dict):
        raw_labels = result.get("error_labels", [])
    else:
        raw_labels = getattr(result, "error_labels", [])
    if isinstance(raw_labels, list):
        return _dedupe([str(label) for label in raw_labels])
    return []


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
