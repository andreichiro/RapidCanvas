"""GEPA scoring helpers for dry-run metadata and optimizer feedback."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_MISSING = object()


@dataclass(frozen=True)
class GepaMetricParts:
    """Inputs to the blended GEPA optimization metric."""

    expected_point_recall: float
    citation_coverage: float
    requirement_following: float
    prompt_injection_resistance: float
    fallback_correctness: float
    hallucination_count: float = 0.0
    unsupported_claim_rate: float = 0.0


def combined_gepa_metric(parts: GepaMetricParts) -> float:
    """Blend quality, citation, safety, and fallback correctness for GEPA."""

    positive = (
        0.25 * parts.expected_point_recall
        + 0.2 * parts.citation_coverage
        + 0.18 * parts.requirement_following
        + 0.22 * parts.prompt_injection_resistance
        + 0.15 * parts.fallback_correctness
    )
    penalty = (
        0.18 * min(1.0, parts.hallucination_count) + 0.24 * parts.unsupported_claim_rate
    )
    return round(max(0.0, min(1.0, positive - penalty)), 4)


def textual_feedback(missing_points: list[str], unsupported_claims: list[str]) -> str:
    """Return the feedback text passed to GEPA traces."""

    feedback: list[str] = []
    if missing_points:
        feedback.append("Missing expected points: " + "; ".join(missing_points))
    if unsupported_claims:
        feedback.append("Unsupported claims: " + "; ".join(unsupported_claims))
    return "\n".join(feedback) or "Prediction satisfies expected points and support checks."


def gepa_feedback_metric(
    module_inputs: Any,
    module_outputs: Any,
    captured_trace: Any = _MISSING,
    pred_name: str | None = None,
    trace_for_pred: Any = None,
) -> float | dict[str, float | str]:
    """Score GEPA predictions against curated points and citation expectations."""

    feedback_requested = captured_trace is not _MISSING
    del captured_trace, pred_name, trace_for_pred
    expected_points = _expected_list(module_inputs, "expected_points")
    expected_citations = _expected_list(module_inputs, "citation_source_ids")
    output_text = json.dumps(_prediction_payload(module_outputs), default=str).lower()
    missing = [point for point in expected_points if point.lower() not in output_text]
    missing_citations = [
        f"missing citation/source id {source_id}"
        for source_id in expected_citations
        if source_id.lower() not in output_text
    ]
    point_score = 1.0 - (len(missing) / len(expected_points)) if expected_points else 1.0
    citation_score = (
        1.0 - (len(missing_citations) / len(expected_citations))
        if expected_citations
        else 1.0
    )
    score = 0.75 * point_score + 0.25 * citation_score
    final_score = max(0.0, score)
    if not feedback_requested:
        return final_score
    return {
        "score": final_score,
        "feedback": textual_feedback(missing, missing_citations),
    }


def _expected_list(module_inputs: Any, field: str) -> list[str]:
    value = getattr(module_inputs, field, None)
    if value is None and isinstance(module_inputs, dict):
        value = module_inputs.get(field, [])
    return [str(item) for item in value] if isinstance(value, list) else []


def _prediction_payload(module_outputs: Any) -> Any:
    if hasattr(module_outputs, "toDict"):
        return module_outputs.toDict()
    if hasattr(module_outputs, "__dict__"):
        return module_outputs.__dict__
    return module_outputs
