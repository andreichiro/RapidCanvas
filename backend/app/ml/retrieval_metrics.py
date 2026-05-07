"""Retrieval diagnostics shaped for eval metric consumers."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, cast

from app.ml.boundary import boundary_attr, boundary_text, safe_limit
from app.ml.c2_policy import diagnostic_strings
from app.ml.diagnostics import RetrievalResult, dedupe_values
from app.schemas.domain import ContextDocument, Evidence

_DEFAULT_RECALL_K = 6
_SANITIZATION_WARNING_PREFIXES = (
    "prompt_injection_risk:",
    "retrieval_evidence_",
    "metadata_iter_failed",
    "content_truncated",
    "document_",
    "context_",
    "rag_evidence_",
)
_FALLBACK_REASON_PREFIXES = (
    "qdrant_unavailable_using_in_memory_vector_store:",
    "retrieval_no_documents",
    "retrieval_adapter_failed:",
    "retrieval_failed:",
    "retrieval_unavailable",
    "rag_runtime_failed:",
    "rag_embedding_shape_invalid",
    "rag_query_embedding_shape_invalid",
    "rag_reranker_iter_failed",
    "rag_reranker_invalid_candidates:",
    "rag_documents_iter_failed",
    "rag_documents_invalid:",
    "bluesky_search_failed:",
    "bluesky_search_invalid_item:",
    "web_search_failed:",
    "web_search_invalid_hit:",
    "web_search_missing_url:",
    "search_provider_failed:",
    "search_provider_invalid_documents:",
    "search_provider_result_limit_exceeded:",
    "search_providers_iter_failed",
    "linked_page_iter_failed",
    "linked_page_limit_exceeded:",
    "timeout",
    "http_status:",
    "http_error:",
    "fetch_failed:",
    "extraction_failed:",
    "unsupported_content_type:",
    "empty_extracted_text",
    "redirect_limit_exceeded",
    "redirect_loop_unresolved",
    "dns_resolution_failed:",
    "dns_resolution_empty:",
    "dns_resolution_invalid:",
    "retrieval_diagnostics_failed:",
)


@dataclass(frozen=True)
class RetrievalRecallInput:
    rank: int
    evidence_id: str
    document_id: str
    source_id: str
    source_type: str
    source_url: str
    source_title: str
    retrieval_score: float
    reranker_score: float | None = None


@dataclass(frozen=True)
class SourceChannelCoverage:
    channel: str
    document_ids: list[str] = field(default_factory=list)
    evidence_document_ids: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceDiversity:
    document_id_count: int
    evidence_document_id_count: int
    source_id_count: int
    channel_count: int
    evidence_channel_count: int
    channels: list[str]
    evidence_channels: list[str]


@dataclass(frozen=True)
class RetrievalMetricsDiagnostics:
    top_k: int
    recall_at_6_inputs: list[RetrievalRecallInput]
    evidence_ids: list[str]
    document_ids: list[str]
    source_ids: list[str]
    retrieval_scores: dict[str, float]
    reranker_scores: dict[str, float]
    source_channel_coverage: dict[str, SourceChannelCoverage]
    source_diversity: SourceDiversity
    prompt_injection_flags: list[str]
    sanitization_warnings: list[str]
    private_url_blocks: list[str]
    skipped_or_fallback_provider_reasons: list[str]
    warnings: list[str]


def retrieval_metrics_diagnostics(
    result: RetrievalResult,
    *,
    top_k: int = _DEFAULT_RECALL_K,
) -> RetrievalMetricsDiagnostics:
    """Return serializable retrieval/source-safety inputs without scoring quality."""

    limit = min(safe_limit(top_k) or _DEFAULT_RECALL_K, _DEFAULT_RECALL_K)
    documents = {document.id: document for document in result.documents}
    ranked_evidence = list(result.evidence[:limit])
    recall_inputs = [
        _recall_input(index, evidence, documents, result.diagnostics.reranker_scores)
        for index, evidence in enumerate(ranked_evidence, start=1)
    ]
    coverage = _source_channel_coverage(result.documents, ranked_evidence)
    warnings = dedupe_values([*result.warnings, *result.diagnostics.warnings])
    document_ids = dedupe_values(document.id for document in result.documents)
    evidence_ids = dedupe_values(item.id for item in ranked_evidence)
    source_ids = dedupe_values(item.source_id for item in ranked_evidence)
    rerank_keys = {
        evidence_id: result.diagnostics.reranker_scores.get(evidence_id)
        for evidence_id in evidence_ids
    }
    return RetrievalMetricsDiagnostics(
        top_k=limit,
        recall_at_6_inputs=recall_inputs,
        evidence_ids=evidence_ids,
        document_ids=document_ids,
        source_ids=source_ids,
        retrieval_scores={item.evidence_id: item.retrieval_score for item in recall_inputs},
        reranker_scores=_finite_score_mapping(rerank_keys),
        source_channel_coverage=coverage,
        source_diversity=_source_diversity(coverage),
        prompt_injection_flags=dedupe_values(result.diagnostics.prompt_injection_flags),
        sanitization_warnings=_warnings_with_prefixes(warnings, _SANITIZATION_WARNING_PREFIXES),
        private_url_blocks=dedupe_values(
            [*result.private_url_blocks, *result.diagnostics.private_url_blocks]
        ),
        skipped_or_fallback_provider_reasons=_warnings_with_prefixes(
            warnings, _FALLBACK_REASON_PREFIXES
        ),
        warnings=warnings,
    )


def retrieval_metrics_payload(
    result: RetrievalResult,
    *,
    top_k: int = _DEFAULT_RECALL_K,
) -> dict[str, Any]:
    """JSON-stable payload Dev D can replay in cached eval without live network."""

    diagnostics = retrieval_metrics_diagnostics(result, top_k=top_k)
    payload = asdict(diagnostics)
    payload["source_channel_coverage"] = {
        channel: asdict(summary)
        for channel, summary in diagnostics.source_channel_coverage.items()
    }
    payload["source_diversity"] = asdict(diagnostics.source_diversity)
    return cast(dict[str, Any], payload)


def _recall_input(
    rank: int,
    evidence: Evidence,
    documents: Mapping[str, ContextDocument],
    reranker_scores: Mapping[str, object],
) -> RetrievalRecallInput:
    document = documents.get(evidence.document_id)
    source_type = _document_text(document, "source_type")
    source_url = _document_text(document, "url")
    source_title = _document_text(document, "title")
    return RetrievalRecallInput(
        rank=rank,
        evidence_id=evidence.id,
        document_id=evidence.document_id,
        source_id=evidence.source_id,
        source_type=source_type,
        source_url=source_url,
        source_title=source_title,
        retrieval_score=_finite_score(evidence.score) or 0.0,
        reranker_score=_finite_score(reranker_scores.get(evidence.id)),
    )


def _source_channel_coverage(
    documents: Sequence[ContextDocument],
    evidence: Sequence[Evidence],
) -> dict[str, SourceChannelCoverage]:
    by_document = {document.id: document for document in documents}
    coverage: dict[str, SourceChannelCoverage] = {}
    for document in documents:
        channel = _document_text(document, "source_type") or "unknown"
        summary = coverage.setdefault(channel, SourceChannelCoverage(channel=channel))
        summary.document_ids.append(document.id)
    for item in evidence:
        source_document = by_document.get(item.document_id)
        channel = _document_text(source_document, "source_type") or "unknown"
        summary = coverage.setdefault(channel, SourceChannelCoverage(channel=channel))
        summary.evidence_document_ids.append(item.document_id)
        summary.evidence_ids.append(item.id)
        summary.source_ids.append(item.source_id)
    return {
        channel: SourceChannelCoverage(
            channel=summary.channel,
            document_ids=dedupe_values(summary.document_ids),
            evidence_document_ids=dedupe_values(summary.evidence_document_ids),
            evidence_ids=dedupe_values(summary.evidence_ids),
            source_ids=dedupe_values(summary.source_ids),
        )
        for channel, summary in sorted(coverage.items())
    }


def _source_diversity(coverage: Mapping[str, SourceChannelCoverage]) -> SourceDiversity:
    document_ids = dedupe_values(
        document_id
        for summary in coverage.values()
        for document_id in summary.document_ids
    )
    evidence_document_ids = dedupe_values(
        document_id
        for summary in coverage.values()
        for document_id in summary.evidence_document_ids
    )
    source_ids = dedupe_values(
        source_id
        for summary in coverage.values()
        for source_id in summary.source_ids
    )
    channels = [channel for channel, summary in coverage.items() if summary.document_ids]
    evidence_channels = [
        channel for channel, summary in coverage.items() if summary.evidence_ids
    ]
    return SourceDiversity(
        document_id_count=len(document_ids),
        evidence_document_id_count=len(evidence_document_ids),
        source_id_count=len(source_ids),
        channel_count=len(channels),
        evidence_channel_count=len(evidence_channels),
        channels=channels,
        evidence_channels=evidence_channels,
    )


def _finite_score_mapping(values: Mapping[str, object]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for key, value in values.items():
        score = _finite_score(value)
        if score is not None:
            scores[boundary_text(key, "score_key_text_failed")] = score
    return scores


def _finite_score(value: object) -> float | None:
    try:
        score = float(cast(Any, value))
    except Exception:
        return None
    return score if math.isfinite(score) else None


def _warnings_with_prefixes(values: Sequence[object], prefixes: tuple[str, ...]) -> list[str]:
    return [
        warning
        for warning in dedupe_values(diagnostic_strings(values))
        if warning.startswith(prefixes)
    ]


def _document_text(document: ContextDocument | None, field_name: str) -> str:
    if document is None:
        return ""
    return boundary_text(
        boundary_attr(document, field_name, f"document_{field_name}_field_failed"),
        f"document_{field_name}_text_failed",
    )
