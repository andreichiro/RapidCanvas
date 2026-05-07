"""Deterministic source quality and citation eligibility policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from app.ml.source_quality_signals import (
    SourceQualitySignal,
    build_quality_signals,
    citation_role,
    citation_threshold,
    has_disqualifying_reason,
    source_channel_prior,
)
from app.ml.vector_payloads import metadata_mapping, public_score
from app.schemas.domain import ContextDocument, PostContext

SOURCE_QUALITY_POLICY_VERSION = "source_quality_v1"
__all__ = [
    "SOURCE_QUALITY_POLICY_VERSION",
    "SourceQualityAssessment",
    "SourceQualitySignal",
    "annotate_source_quality",
    "citation_eligible",
    "dedupe_equivalent_documents",
    "score_document_quality",
    "source_channel_prior",
]


@dataclass(frozen=True)
class SourceQualityAssessment:
    """Bounded score plus explainable quality signals."""

    score: float
    reasons: list[str] = field(default_factory=list)
    signals: list[SourceQualitySignal] = field(default_factory=list)


def score_document_quality(
    post: PostContext,
    query: str,
    document: ContextDocument,
) -> SourceQualityAssessment:
    """Score a document as evidence for the target post and query."""

    signals = build_quality_signals(post, query, document)
    score = public_score(sum(signal.weight for signal in signals))
    reasons = [signal.reason for signal in signals if abs(signal.weight) >= 0.04]
    return SourceQualityAssessment(score=round(score, 3), reasons=reasons, signals=signals)


def citation_eligible(
    document: ContextDocument,
    assessment: SourceQualityAssessment,
) -> bool:
    """Return whether a source may support public bullet citations."""

    metadata = metadata_mapping(document.metadata)
    if metadata.get("fetch_success") is False and metadata.get("snippet_only") is not True:
        return False
    if has_disqualifying_reason(assessment.reasons, assessment.score):
        return False
    threshold = citation_threshold(document)
    return threshold is not None and assessment.score >= threshold


def annotate_source_quality(
    post: PostContext,
    query: str,
    documents: list[ContextDocument],
) -> tuple[list[ContextDocument], list[dict[str, Any]]]:
    """Attach score, reasons, and citation eligibility to document metadata."""

    annotated: list[ContextDocument] = []
    trace_rows: list[dict[str, Any]] = []
    for document in documents:
        assessment = score_document_quality(post, query, document)
        eligible = citation_eligible(document, assessment)
        role = citation_role(document, eligible)
        signal_names = [signal.name for signal in assessment.signals]
        metadata = {
            **metadata_mapping(document.metadata),
            "source_quality_policy": SOURCE_QUALITY_POLICY_VERSION,
            "source_quality_score": assessment.score,
            "source_quality_reasons": assessment.reasons,
            "source_quality_signals": signal_names,
            "citation_eligible": eligible,
            "citation_role": role,
        }
        annotated.append(document.model_copy(update={"metadata": metadata}))
        trace_rows.append(_trace_row(document, assessment, signal_names, eligible, role))
    return annotated, trace_rows


def dedupe_equivalent_documents(documents: list[ContextDocument]) -> list[ContextDocument]:
    """Deduplicate equivalent web documents while keeping the strongest evidence copy."""

    winners: dict[str, ContextDocument] = {}
    order: list[str] = []
    for document in documents:
        key = _equivalence_key(document)
        if key not in winners:
            winners[key] = document
            order.append(key)
            continue
        winners[key] = _better_document(winners[key], document)
    return [winners[key] for key in order]


def _trace_row(
    document: ContextDocument,
    assessment: SourceQualityAssessment,
    signal_names: list[str],
    eligible: bool,
    role: str,
) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "url": document.url,
        "source_type": document.source_type,
        "quality_score": assessment.score,
        "quality_reasons": assessment.reasons,
        "quality_signals": signal_names,
        "citation_eligible": eligible,
        "citation_role": role,
    }


def _equivalence_key(document: ContextDocument) -> str:
    if document.source_type != "web":
        return f"{document.source_type}:{document.id}"
    try:
        parsed = urlsplit(document.url)
    except ValueError:
        return f"web:{document.id}"
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    if not host:
        return f"web:{document.id}"
    return f"web:{urlunsplit((parsed.scheme.lower(), host, path, '', ''))}"


def _better_document(left: ContextDocument, right: ContextDocument) -> ContextDocument:
    return right if _document_priority(right) > _document_priority(left) else left


def _document_priority(document: ContextDocument) -> tuple[float, float, float, float, float]:
    metadata = metadata_mapping(document.metadata)
    return (
        1.0 if metadata.get("linked_from_post") is True else 0.0,
        1.0 if metadata.get("citation_eligible") is True else 0.0,
        1.0 if metadata.get("snippet_only") is not True else 0.0,
        public_score(metadata.get("source_quality_score", 0.0)),
        _float_or_zero(metadata.get("extracted_length")),
    )


def _float_or_zero(value: object) -> float:
    try:
        return max(0.0, float(value))  # type: ignore[arg-type]
    except Exception:
        return 0.0
