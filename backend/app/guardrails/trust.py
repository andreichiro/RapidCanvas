"""Trust scoring and fallback selection for evidence-backed explanations."""

from __future__ import annotations

from collections.abc import Sequence

from app.guardrails.policies import DEFAULT_POLICY, GuardrailPolicy
from app.schemas.domain import Evidence, FallbackMode, PostContext, TrustAssessment


class TrustScorer:
    """Combine evidence quality, source diversity, and guardrail signals."""

    def __init__(self, policy: GuardrailPolicy = DEFAULT_POLICY) -> None:
        self._policy = policy

    def assess(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        *,
        guardrail_flags: Sequence[str] = (),
        validation_issues: Sequence[str] = (),
    ) -> TrustAssessment:
        """Return a normalized trust score and fallback decision."""

        diversity_score = _source_diversity_score(evidence)
        retrieval_score = _retrieval_score(evidence)
        score = _base_score(len(evidence), diversity_score, retrieval_score)
        flags, reasons = _evidence_findings(evidence, diversity_score, retrieval_score)
        score += _guardrail_delta(guardrail_flags, flags, reasons)
        score += _validation_delta(validation_issues, flags, reasons)
        score = max(0.0, min(1.0, score))
        fallback_mode = self._fallback_mode(post, score, flags)
        if fallback_mode != "none" and not reasons:
            reasons.append(f"Trust score {score:.2f} requires {fallback_mode} fallback.")

        return TrustAssessment(
            score=round(score, 3),
            fallback_mode=fallback_mode,
            flags=_dedupe(flags),
            reasons=_dedupe(reasons),
        )

    def _fallback_mode(
        self,
        post: PostContext,
        score: float,
        flags: list[str],
    ) -> FallbackMode:
        dspy_mode = _dspy_requested_fallback(flags)
        if dspy_mode is not None:
            return dspy_mode
        if _must_abstain(post, score, flags):
            return "abstain"
        return _policy_fallback_mode(
            score=score,
            flags=flags,
            min_partial_trust=self._policy.min_partial_trust,
            min_normal_trust=self._policy.min_normal_trust,
        )


def _base_score(count: int, diversity_score: float, retrieval_score: float) -> float:
    evidence_score = _evidence_count_score(count)
    return 0.36 * evidence_score + 0.28 * diversity_score + 0.36 * retrieval_score


def _dspy_requested_fallback(flags: list[str]) -> FallbackMode | None:
    ordered_modes: tuple[FallbackMode, ...] = ("abstain", "safe_summary", "partial")
    for mode in ordered_modes:
        if f"dspy_trust_{mode}" in flags:
            return mode
    return None


def _policy_fallback_mode(
    *,
    score: float,
    flags: list[str],
    min_partial_trust: float,
    min_normal_trust: float,
) -> FallbackMode:
    if any(
        flag in flags
        for flag in ("invalid_output_shape", "unknown_citation", "uncited_output")
    ):
        return "partial"
    if "prompt_injection_risk" in flags and score < min_normal_trust:
        return "safe_summary"
    if "conflicting_sources" in flags:
        return "partial"
    if score < min_partial_trust:
        return "safe_summary"
    if score < min_normal_trust:
        return "partial"
    return "none"


def _evidence_findings(
    evidence: Sequence[Evidence],
    diversity_score: float,
    retrieval_score: float,
) -> tuple[list[str], list[str]]:
    flags: list[str] = []
    reasons: list[str] = []
    if not evidence:
        flags.append("low_evidence")
        reasons.append("No retrieved evidence was available.")
    elif len(evidence) < 3:
        flags.append("low_evidence")
        reasons.append("Fewer than three evidence chunks were available.")
    if diversity_score < 0.67:
        flags.append("low_source_diversity")
        reasons.append("Evidence comes from too few distinct sources.")
    if retrieval_score < 0.45:
        flags.append("weak_retrieval_score")
        reasons.append("Retrieved evidence scores are weak.")
    return flags, reasons


def _guardrail_delta(
    guardrail_flags: Sequence[str],
    flags: list[str],
    reasons: list[str],
) -> float:
    delta = 0.0
    for flag in guardrail_flags:
        if flag not in flags:
            flags.append(flag)
        delta += _guardrail_penalty(flag, reasons)
    return delta


def _guardrail_penalty(flag: str, reasons: list[str]) -> float:
    if flag.startswith("dspy_trust_"):
        mode = flag.removeprefix("dspy_trust_")
        reasons.append(f"DSPy trust assessment requested {mode} fallback.")
        return {
            "abstain": -1.0,
            "safe_summary": -0.5,
            "partial": -0.25,
        }.get(mode, -0.1)
    if flag == "prompt_injection_risk":
        reasons.append("Prompt-injection markers were detected in untrusted content.")
        return -0.18
    if flag == "conflicting_sources":
        reasons.append("Evidence contains contradiction markers.")
        return -0.22
    return 0.0


def _validation_delta(
    validation_issues: Sequence[str],
    flags: list[str],
    reasons: list[str],
) -> float:
    delta = 0.0
    for issue in validation_issues:
        delta += _validation_penalty(issue, flags, reasons)
    return delta


def _validation_penalty(issue: str, flags: list[str], reasons: list[str]) -> float:
    penalties = {
        "uncited_output": ("uncited_output", -0.25, "A generated bullet lacked a citation."),
        "leaked_instruction_or_secret": (
            "leaked_instruction_or_secret",
            -0.35,
            "A generated bullet echoed unsafe instruction-like content.",
        ),
        "invalid_bullet_count": (
            "invalid_output_shape",
            -0.12,
            "The generated explanation had the wrong bullet count.",
        ),
        "unknown_citation": (
            "unknown_citation",
            -0.2,
            "A generated bullet cited an unknown source.",
        ),
    }
    if issue not in penalties:
        return 0.0
    flag, penalty, reason = penalties[issue]
    flags.append(flag)
    reasons.append(reason)
    return penalty


def _must_abstain(post: PostContext, score: float, flags: list[str]) -> bool:
    if not post.text.strip() and "low_evidence" in flags:
        return True
    return "leaked_instruction_or_secret" in flags or score < 0.25


def _evidence_count_score(count: int) -> float:
    if count <= 0:
        return 0.0
    return min(1.0, count / 3)


def _source_diversity_score(evidence: Sequence[Evidence]) -> float:
    if not evidence:
        return 0.0
    distinct_sources = {item.source_id for item in evidence}
    return min(1.0, len(distinct_sources) / 3)


def _retrieval_score(evidence: Sequence[Evidence]) -> float:
    if not evidence:
        return 0.0
    average = sum(min(1.0, max(0.0, item.score)) for item in evidence) / len(evidence)
    return min(1.0, average)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
