"""Trust scoring and fallback selection for evidence-backed explanations."""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite

from app.guardrails.policies import DEFAULT_POLICY, GuardrailPolicy
from app.schemas.domain import ContextDocument, Evidence, FallbackMode, PostContext, TrustAssessment


class TrustScorer:
    """Combine evidence quality, source diversity, and guardrail signals."""

    def __init__(self, policy: GuardrailPolicy = DEFAULT_POLICY) -> None:
        self._policy = policy

    def assess(
        self,
        post: PostContext,
        evidence: Sequence[Evidence],
        *,
        documents: Sequence[ContextDocument] = (),
        guardrail_flags: Sequence[str] = (),
        validation_issues: Sequence[str] = (),
    ) -> TrustAssessment:
        """Return a normalized trust score and fallback decision."""

        diversity_score = _source_diversity_score(evidence)
        retrieval_score = _retrieval_score(evidence)
        score = _base_score(len(evidence), diversity_score, retrieval_score)
        flags, reasons = _evidence_findings(
            evidence,
            diversity_score,
            retrieval_score,
            documents=documents,
        )
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
        for flag in (
            "invalid_output_shape",
            "unknown_citation",
            "uncited_output",
            "non_english_output",
            "unsupported_claim",
            "unsafe_echo",
            "weak_citation_support",
            "off_topic_citation",
            "needs_primary_source",
            "weak_source_quality",
            "ineligible_citation",
            "snippet_only_citation",
        )
    ):
        return "partial"
    if "dspy_provider_error" in flags:
        return "safe_summary"
    if "prompt_injection_risk" in flags and score < min_normal_trust:
        return "safe_summary"
    if "conflicting_sources" in flags:
        return "partial"
    if "weak_retrieval_score" in flags:
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
    *,
    documents: Sequence[ContextDocument] = (),
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
    if _has_contradiction_markers(evidence):
        flags.append("conflicting_sources")
        reasons.append("Evidence contains contradiction markers.")
    _source_quality_findings(evidence, documents, flags, reasons)
    return flags, reasons


def _source_quality_findings(
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
    flags: list[str],
    reasons: list[str],
) -> None:
    cited_documents = _cited_documents(evidence, documents)
    if not cited_documents:
        return
    quality_scores = [
        score
        for document in cited_documents
        if (score := _metadata_score(document.metadata.get("source_quality_score"))) is not None
    ]
    if quality_scores and sum(quality_scores) / len(quality_scores) < 0.45:
        flags.append("weak_source_quality")
        reasons.append("Cited evidence has weak source-quality scores.")
    if any(document.metadata.get("citation_eligible") is False for document in cited_documents):
        flags.append("ineligible_citation")
        reasons.append("At least one cited source is not eligible for public citation.")
    reason_text = " ".join(
        str(reason).lower()
        for document in cited_documents
        for reason in _metadata_reasons(document.metadata.get("source_quality_reasons"))
    )
    if "off_topic" in reason_text:
        flags.append("off_topic_citation")
        reasons.append("At least one cited source is off topic for the claim.")
    if _all_public_sources_are_snippet_only(cited_documents):
        flags.append("snippet_only_citation")
        reasons.append("Only snippet-level search evidence supports the cited claims.")


def _cited_documents(
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
) -> list[ContextDocument]:
    by_id = {document.id: document for document in documents}
    cited: list[ContextDocument] = []
    for item in evidence:
        document = by_id.get(item.document_id) or by_id.get(item.source_id)
        if document is not None:
            cited.append(document)
    return cited


def _metadata_score(value: object) -> float | None:
    try:
        score = float(value)  # type: ignore[arg-type]
    except Exception:
        return None
    if not isfinite(score):
        return None
    return min(1.0, max(0.0, score))


def _metadata_reasons(value: object) -> list[str]:
    if isinstance(value, list):
        return [reason for reason in value if isinstance(reason, str)]
    if isinstance(value, str):
        return [value]
    return []


def _all_public_sources_are_snippet_only(documents: Sequence[ContextDocument]) -> bool:
    public_documents = [
        document for document in documents if document.source_type in {"web", "bluesky"}
    ]
    return bool(public_documents) and all(
        document.metadata.get("snippet_only") is True for document in public_documents
    )


def _guardrail_delta(
    guardrail_flags: Sequence[str],
    flags: list[str],
    reasons: list[str],
) -> float:
    delta = 0.0
    for flag in _dedupe(guardrail_flags):
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
    if flag == "dspy_provider_error":
        reasons.append("DSPy provider failed; guarded deterministic fallback was used.")
        return -0.5
    if flag == "conflicting_sources":
        reasons.append("Evidence contains contradiction markers.")
        return -0.22
    if flag in {"private_url_blocked", "unsafe_source"} or flag.startswith("source_safety_"):
        reasons.append("Source-safety diagnostics downgraded trust.")
        return -0.2
    return 0.0


def _validation_delta(
    validation_issues: Sequence[str],
    flags: list[str],
    reasons: list[str],
) -> float:
    return sum(_validation_penalty(issue, flags, reasons) for issue in _dedupe(validation_issues))


def _validation_penalty(issue: str, flags: list[str], reasons: list[str]) -> float:
    penalties = {
        "uncited_output": ("uncited_output", -0.25, "A generated bullet lacked a citation."),
        "leaked_instruction_or_secret": (
            "leaked_instruction_or_secret",
            -0.35,
            "A generated bullet echoed unsafe instruction-like content.",
        ),
        "unsafe_echo": (
            "unsafe_echo",
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
        "non_english_output": (
            "non_english_output",
            -0.2,
            "A generated bullet was not written in English.",
        ),
        "unsupported_claim": (
            "unsupported_claim",
            -0.25,
            "A generated factual claim was not supported by its citations.",
        ),
        "weak_citation_support": (
            "weak_citation_support",
            -0.18,
            "A cited source weakly supported the generated bullet.",
        ),
        "off_topic_citation": (
            "off_topic_citation",
            -0.2,
            "A cited source appeared off topic for the generated bullet.",
        ),
        "needs_primary_source": (
            "needs_primary_source",
            -0.18,
            "A broad claim needed stronger primary-source support.",
        ),
    }
    if issue not in penalties:
        return 0.0
    flag, penalty, reason = penalties[issue]
    flags.append(flag)
    reasons.append(reason)
    return penalty


def _must_abstain(post: PostContext, score: float, flags: list[str]) -> bool:
    unsafe = bool({"leaked_instruction_or_secret", "unsafe_echo"} & set(flags))
    no_visible_text = not post.text.strip()
    return unsafe or (no_visible_text and ("low_evidence" in flags or score < 0.25))


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
    average = sum(_bounded_score(item.score) for item in evidence) / len(evidence)
    return min(1.0, average)


def _bounded_score(value: float) -> float:
    score = float(value)
    if not isfinite(score):
        return 0.0
    return min(1.0, max(0.0, score))


def _has_contradiction_markers(evidence: Sequence[Evidence]) -> bool:
    markers = (
        "contradicts",
        "contradiction",
        "conflicting source",
        "disputes this",
        "directly disputes",
    )
    return any(marker in item.text.lower() for item in evidence for marker in markers)


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
