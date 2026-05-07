"""Guarded RAG runtime calls for optional provider boundaries."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import replace
from typing import Any, Protocol, TypeVar, cast

from app.ml.boundary import boundary_attr, boundary_text, bounded_items, safe_limit
from app.ml.rerankers import RerankCandidate
from app.ml.vector_payloads import public_score
from app.schemas.domain import Evidence


class _ChunkLike(Protocol):
    @property
    def text(self) -> str: ...


T = TypeVar("T", bound=_ChunkLike)


def ranked_rag_candidates(
    *,
    query_text: str,
    chunks: Sequence[T],
    namespace: str,
    embedding_provider: Any,
    vector_store: Any,
    reranker: Any,
    retrieve_limit: int,
    evidence_limit: int,
) -> tuple[list[RerankCandidate[T]], list[str]]:
    warnings: list[str] = []
    ranked: list[RerankCandidate[T]] = []
    namespace_opened = False
    try:
        chunk_embeddings = embedding_provider.embed([chunk.text for chunk in chunks])
        if not _valid_embedding_batch(chunk_embeddings, len(chunks)):
            return [], ["rag_embedding_shape_invalid"]
        vector_store.ensure_collection(vector_size=len(chunk_embeddings[0]))
        namespace_opened = True
        vector_store.upsert(namespace, chunks, chunk_embeddings)
        query_embeddings = embedding_provider.embed([query_text])
        if not _valid_embedding_batch(query_embeddings, 1):
            warnings.append("rag_query_embedding_shape_invalid")
            return [], warnings
        search_results = vector_store.query(
            namespace,
            query_embeddings[0],
            limit=min(retrieve_limit, len(chunks)),
        )
        candidates: list[RerankCandidate[T]] = [
            RerankCandidate(
                item=_with_vector_score(result.chunk, result.score),
                score=result.score,
            )
            for result in search_results
        ]
        ranked = reranker.rerank(query_text, candidates, limit=evidence_limit)
        ranked, reranker_warnings = _safe_ranked_candidates(ranked, candidates, evidence_limit)
        warnings.extend(reranker_warnings)
        return _quality_adjusted_candidates(ranked, evidence_limit), warnings
    except Exception as exc:
        warnings.append(f"rag_runtime_failed:{exc.__class__.__name__}")
        return [], warnings
    finally:
        if namespace_opened:
            try:
                vector_store.clear_namespace(namespace)
            except Exception as exc:
                warnings.append(f"rag_namespace_clear_failed:{exc.__class__.__name__}")


def _valid_embedding_batch(value: object, expected_count: int) -> bool:
    if not isinstance(value, list) or len(value) != expected_count:
        return False
    return all(isinstance(vector, list) and len(vector) > 0 for vector in value)


def _safe_ranked_candidates(
    value: object,
    fallback: list[RerankCandidate[T]],
    limit: int,
) -> tuple[list[RerankCandidate[T]], list[str]]:
    limit_value = safe_limit(limit)
    fallback_safe: list[RerankCandidate[T]] = _chunk_candidates(fallback)
    items, warnings = bounded_items(value, limit_value, "rag_reranker_iter_failed")
    ranked: list[RerankCandidate[T]] = _chunk_candidates(items)
    if invalid_count := len(items) - len(ranked):
        warnings.append(f"rag_reranker_invalid_candidates:{invalid_count}")
    if warnings:
        return fallback_safe[:limit_value], warnings
    return ranked[:limit_value], []


def _chunk_candidates(items: Sequence[object]) -> list[RerankCandidate[T]]:
    return [
        candidate
        for candidate in items
        if isinstance(candidate, RerankCandidate) and _has_chunk_item(candidate.item)
    ]


def _quality_adjusted_candidates(
    candidates: Sequence[RerankCandidate[T]],
    limit: int,
) -> list[RerankCandidate[T]]:
    adjusted = [
        RerankCandidate(
            item=candidate.item,
            score=_combined_candidate_score(candidate),
        )
        for candidate in candidates
    ]
    return sorted(
        adjusted,
        key=lambda candidate: (
            candidate.score,
            _chunk_quality_score(candidate.item),
            _chunk_channel_prior(candidate.item),
        ),
        reverse=True,
    )[: safe_limit(limit)]


def _combined_candidate_score(candidate: RerankCandidate[T]) -> float:
    vector = _chunk_vector_score(candidate.item, candidate.score)
    reranker = public_score(candidate.score)
    quality = _chunk_quality_score(candidate.item)
    channel_prior = _chunk_channel_prior(candidate.item)
    return public_score(0.25 * vector + 0.20 * reranker + 0.45 * quality + 0.10 * channel_prior)


def _with_vector_score(item: T, score: float) -> T:
    metadata = getattr(item, "metadata", {})
    if not isinstance(metadata, dict):
        return item
    try:
        return cast(
            T,
            replace(
                cast(Any, item),
                metadata={**metadata, "vector_score": public_score(score)},
            ),
        )
    except Exception:
        return item


def _chunk_vector_score(item: object, fallback: float) -> float:
    metadata = getattr(item, "metadata", {})
    if not isinstance(metadata, dict):
        return public_score(fallback)
    return public_score(metadata.get("vector_score", fallback))


def _chunk_quality_score(item: object) -> float:
    metadata = getattr(item, "metadata", {})
    if not isinstance(metadata, dict):
        return 0.5
    return public_score(metadata.get("source_quality_score", 0.5))


def _chunk_channel_prior(item: object) -> float:
    metadata = getattr(item, "metadata", {})
    source_type = ""
    if isinstance(metadata, dict):
        source_type = boundary_text(metadata.get("source_type", ""), "source_type_text_failed")
    return {
        "thread": 0.92,
        "image": 0.72,
        "bluesky": 0.66,
        "web": 0.5,
    }.get(source_type, 0.4)


def _has_chunk_item(value: object) -> bool:
    return all(_has_attr(value, name) for name in ("document_id", "source_id", "text"))


def _has_attr(value: object, name: str) -> bool:
    try:
        getattr(value, name)
    except Exception:
        return False
    return True


def evidence_from_ranked_candidates(
    ranked: Sequence[RerankCandidate[T]],
    document_ids: set[str],
) -> tuple[list[Evidence], list[str], dict[str, float]]:
    evidence: list[Evidence] = []
    scores: dict[str, float] = {}
    warnings: list[str] = []
    for index, candidate in enumerate(ranked, start=1):
        document_id, bad_document_id = _chunk_field(candidate.item, "document_id")
        source_id, bad_source_id = _chunk_field(candidate.item, "source_id")
        text, bad_text = _chunk_field(candidate.item, "text")
        if not (document_id.strip() and source_id.strip() and text.strip()):
            warnings.append(f"rag_evidence_invalid_candidate:{index}")
            continue
        if bad_document_id or bad_source_id or bad_text:
            warnings.append(f"rag_evidence_invalid_candidate:{index}")
            continue
        if document_id not in document_ids or source_id not in document_ids:
            warnings.append(f"rag_evidence_orphaned_candidate:{index}")
            continue
        evidence_id = f"E{len(evidence) + 1}"
        evidence.append(
            Evidence(
                id=evidence_id,
                document_id=document_id,
                text=text,
                score=public_score(candidate.score),
                source_id=source_id,
            )
        )
        if (score := _finite_float(candidate.score)) is not None:
            scores[evidence_id] = score
    return evidence, warnings, scores


def _finite_float(value: object) -> float | None:
    try:
        score = float(cast(Any, value))
    except Exception:
        return None
    return score if math.isfinite(score) else None


def _chunk_field(item: object, name: str) -> tuple[str, bool]:
    field_prefix = f"rag_{name}_field_failed"
    text_prefix = f"rag_{name}_text_failed"
    raw = boundary_attr(item, name, field_prefix)
    text = boundary_text(raw, text_prefix)
    return text, text.startswith(f"{field_prefix}:") or text.startswith(f"{text_prefix}:")
