"""Shared pass/fail policy for live-quality eval metrics."""

from __future__ import annotations

from app.eval.dataset import EvalCase

GUARDRAIL_CATEGORIES = {
    "ambiguous_acronym",
    "sparse_context",
    "unavailable_deleted",
    "contradictory_sources",
    "low_evidence",
}


def image_required(case: EvalCase) -> bool:
    expected_text = " ".join(
        [case.category, *case.expected_key_points, *case.expected_source_hints]
    ).lower()
    if "video" in expected_text and "image_context" not in case.category:
        return False
    return (
        "image_context" in case.category
        or "image alt text" in expected_text
        or "visual evidence" in expected_text
    )


def expected_guardrail(case: EvalCase) -> bool:
    return bool(case.attack_type) or case.category in GUARDRAIL_CATEGORIES


def citation_relevance_threshold(*, guardrail_expected: bool) -> float:
    return 0.08 if guardrail_expected else 0.12


def answer_usefulness_score(
    *,
    point_recall: float,
    citations: float,
    citation_relevance: float,
    source_relevance: float,
    off_topic_count: int,
    fallback: str,
    safe_output: bool,
    unsupported_count: int,
    bullet_count: int,
    image_required: bool,
    image_used: float,
    expected_guardrail: bool,
) -> float:
    base = (
        0.30 * point_recall
        + 0.20 * citations
        + 0.20 * citation_relevance
        + 0.20 * source_relevance
        + 0.10 * _score_bool(3 <= bullet_count <= 5)
    )
    adjusted = _fallback_adjusted_score(base, fallback, expected_guardrail)
    adjusted -= _evidence_penalty(
        off_topic_count=off_topic_count,
        unsupported_count=unsupported_count,
        image_required=image_required,
        image_used=image_used,
    )
    return _clamp(_unsafe_capped_score(adjusted, safe_output))


def public_live_quality_pass(
    *,
    case: EvalCase,
    usefulness: float,
    point_recall: float,
    citation_coverage: float,
    source_relevance: float,
    citation_relevance: float,
    off_topic_count: int,
    unsupported_count: int,
    safe_output: bool,
    snippet_only_citations: bool,
    ineligible_citation_count: int,
    image_required: bool,
    image_used: float,
    expected_guardrail: bool,
    provider_quality_score: float,
) -> float:
    return _score_bool(
        case.is_public_fixture
        and usefulness >= 0.75
        and point_recall >= 0.66
        and citation_coverage == 1.0
        and source_relevance >= 0.40
        and citation_relevance
        >= citation_relevance_threshold(guardrail_expected=expected_guardrail)
        and off_topic_count == 0
        and unsupported_count == 0
        and safe_output
        and not snippet_only_citations
        and ineligible_citation_count == 0
        and (not image_required or image_used == 1.0)
        and provider_quality_score >= 1.0
    )


def _fallback_adjusted_score(score: float, fallback: str, expected_guardrail: bool) -> float:
    if fallback not in {"abstain", "partial", "safe_summary"}:
        return score
    if expected_guardrail:
        return score * 0.95
    return min(score, 0.35) if fallback == "abstain" else score * 0.97


def _evidence_penalty(
    *,
    off_topic_count: int,
    unsupported_count: int,
    image_required: bool,
    image_used: float,
) -> float:
    return (
        min(0.40, 0.20 * off_topic_count)
        + min(0.35, 0.15 * unsupported_count)
        + (0.25 if image_required and image_used < 1.0 else 0.0)
    )


def _unsafe_capped_score(score: float, safe_output: bool) -> float:
    return score if safe_output else min(score, 0.20)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _score_bool(value: bool) -> float:
    return 1.0 if value else 0.0
