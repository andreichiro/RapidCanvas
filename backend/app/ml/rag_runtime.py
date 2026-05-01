"""Guarded RAG runtime calls for optional provider boundaries."""

from __future__ import annotations

import math
from collections.abc import Sequence
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
    embedding_provider: Any,
    vector_store: Any,
    reranker: Any,
    retrieve_limit: int,
    evidence_limit: int,
) -> tuple[list[RerankCandidate[T]], list[str]]:
    try:
        chunk_embeddings = embedding_provider.embed([chunk.text for chunk in chunks])
        if not _valid_embedding_batch(chunk_embeddings, len(chunks)):
            return [], ["rag_embedding_shape_invalid"]
        vector_store.recreate_collection(vector_size=len(chunk_embeddings[0]))
        vector_store.upsert(chunks, chunk_embeddings)
        query_embeddings = embedding_provider.embed([query_text])
        if not _valid_embedding_batch(query_embeddings, 1):
            return [], ["rag_query_embedding_shape_invalid"]
        search_results = vector_store.query(
            query_embeddings[0],
            limit=min(retrieve_limit, len(chunks)),
        )
        candidates: list[RerankCandidate[T]] = [
            RerankCandidate(item=result.chunk, score=result.score) for result in search_results
        ]
        ranked = reranker.rerank(query_text, candidates, limit=evidence_limit)
        return _safe_ranked_candidates(ranked, candidates, evidence_limit)
    except Exception as exc:
        return [], [f"rag_runtime_failed:{exc.__class__.__name__}"]


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
        candidate for candidate in items
        if isinstance(candidate, RerankCandidate) and _has_chunk_item(candidate.item)
    ]


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
