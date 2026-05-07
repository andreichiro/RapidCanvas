"""Small capped adaptive retrieval helpers for the runtime path."""

from __future__ import annotations

from collections.abc import Sequence

from app.agent.evidence_contract import EvidenceBundle
from app.guardrails.policies import DEFAULT_POLICY
from app.guardrails.trust import TrustScorer
from app.schemas.domain import ContextDocument, Evidence, PostContext


def should_run_adaptive_round(post: PostContext, bundle: EvidenceBundle) -> tuple[bool, float]:
    assessment = TrustScorer().assess(post, bundle.evidence, guardrail_flags=bundle.guardrail_flags)
    weak_quality = (
        len(bundle.evidence) < 3
        or len({item.source_id for item in bundle.evidence}) < 3
        or _average_evidence_score(bundle.evidence) < 0.45
        or "retrieval_unavailable" in bundle.guardrail_flags
        or _has_source_safety_pressure(bundle)
    )
    return weak_quality and assessment.score < DEFAULT_POLICY.min_normal_trust, assessment.score


def merge_bundles(first: EvidenceBundle, second: EvidenceBundle) -> EvidenceBundle:
    documents = _dedupe_documents([*first.documents, *second.documents])
    evidence = _dedupe_evidence([*first.evidence, *second.evidence])
    return EvidenceBundle(
        evidence=tuple(sorted(evidence, key=lambda item: item.score, reverse=True)),
        documents=tuple(documents),
        warnings=tuple(_dedupe([*first.warnings, *second.warnings])),
        guardrail_flags=tuple(_dedupe([*first.guardrail_flags, *second.guardrail_flags])),
        source_safety_diagnostics=tuple(
            _dedupe([*first.source_safety_diagnostics, *second.source_safety_diagnostics])
        ),
    )


def _average_evidence_score(evidence: Sequence[Evidence]) -> float:
    if not evidence:
        return 0.0
    return sum(max(0.0, min(1.0, item.score)) for item in evidence) / len(evidence)


def _has_source_safety_pressure(bundle: EvidenceBundle) -> bool:
    return bool(bundle.source_safety_diagnostics) or any(
        flag == "prompt_injection_risk"
        or flag in {"private_url_blocked", "unsafe_source"}
        or flag.startswith("source_safety_")
        for flag in bundle.guardrail_flags
    )


def _dedupe_documents(documents: Sequence[ContextDocument]) -> list[ContextDocument]:
    by_id: dict[str, ContextDocument] = {}
    for document in documents:
        by_id.setdefault(document.id, document)
    return list(by_id.values())


def _dedupe_evidence(evidence: Sequence[Evidence]) -> list[Evidence]:
    by_id: dict[str, Evidence] = {}
    for item in evidence:
        existing = by_id.get(item.id)
        if existing is None or item.score > existing.score:
            by_id[item.id] = item
    return list(by_id.values())


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped
