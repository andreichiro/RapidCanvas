"""Rerankers for retrieved evidence candidates."""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from app.ml.boundary import boundary_text, safe_limit

T = TypeVar("T")


@dataclass(frozen=True)
class RerankCandidate(Generic[T]):
    """Candidate item plus its retrieval score."""

    item: T
    score: float


class Reranker(Protocol[T]):
    """Reranker boundary shared by vector retrieval and optional ML rerankers."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate[T]],
        limit: int,
    ) -> list[RerankCandidate[T]]:
        """Return candidates ordered by relevance."""


class SimilarityReranker(Generic[T]):
    """Fallback reranker that preserves vector similarity ordering."""

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate[T]],
        limit: int,
    ) -> list[RerankCandidate[T]]:
        """Sort by score descending."""

        del query
        limit_value = safe_limit(limit)
        if limit_value == 0:
            return []
        ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
        return ranked[:limit_value]


class CrossEncoderReranker(Generic[T]):
    """Optional Hugging Face cross-encoder reranker."""

    def __init__(
        self,
        model_name: str = "cross-encoder/ms-marco-MiniLM-L6-v2",
        model: object | None = None,
    ) -> None:
        if model is None:
            sentence_transformers: Any = importlib.import_module("sentence_transformers")
            model = sentence_transformers.CrossEncoder(model_name)
        self._model = model
        self._fallback: SimilarityReranker[T] = SimilarityReranker()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate[T]],
        limit: int,
    ) -> list[RerankCandidate[T]]:
        """Score query/text pairs with a cross-encoder."""

        limit_value = safe_limit(limit)
        if limit_value == 0 or not candidates:
            return []
        query_text = boundary_text(query, "rerank_query_text_failed")
        pairs = [(query_text, _candidate_text(candidate.item)) for candidate in candidates]
        model: Any = self._model
        try:
            scores = [float(score) for score in model.predict(pairs)]
            rescored = [
                RerankCandidate(item=candidate.item, score=score)
                for candidate, score in zip(candidates, scores, strict=True)
            ]
        except Exception:
            return self._fallback.rerank(query_text, candidates, limit_value)
        ranked = sorted(rescored, key=lambda candidate: candidate.score, reverse=True)
        return ranked[:limit_value]


class DSPyReranker(Generic[T]):
    """Optional DSPy LLM reranker that falls back to similarity on parse failure."""

    def __init__(self, predictor: object | None = None) -> None:
        self._predictor: Any = predictor or self._build_predictor()
        self._fallback: SimilarityReranker[T] = SimilarityReranker()

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate[T]],
        limit: int,
    ) -> list[RerankCandidate[T]]:
        """Ask DSPy for ranked candidate IDs and preserve a deterministic fallback."""

        limit_value = safe_limit(limit)
        if limit_value == 0 or not candidates:
            return []
        query_text = boundary_text(query, "rerank_query_text_failed")
        candidate_payload = [
            {
                "id": _candidate_id(candidate.item),
                "text": _candidate_text(candidate.item),
                "score": candidate.score,
            }
            for candidate in candidates
        ]
        try:
            prediction = self._predictor(
                query=query_text,
                candidates=json.dumps(candidate_payload, ensure_ascii=True),
            )
            ranked_ids_text = boundary_text(
                getattr(prediction, "ranked_ids", "[]"),
                "rerank_ranked_ids_text_failed",
            )
            ranked_ids = json.loads(ranked_ids_text)
        except Exception:
            return self._fallback.rerank(query_text, candidates, limit_value)
        if not isinstance(ranked_ids, list):
            return self._fallback.rerank(query_text, candidates, limit_value)

        by_id = {_candidate_id(candidate.item): candidate for candidate in candidates}
        ranked: list[RerankCandidate[T]] = []
        for candidate_id in ranked_ids:
            candidate = by_id.get(boundary_text(candidate_id, "rerank_ranked_id_failed"))
            if candidate is not None and candidate not in ranked:
                ranked.append(candidate)
        ranked.extend(candidate for candidate in candidates if candidate not in ranked)
        return ranked[:limit_value]

    def _build_predictor(self) -> Any:
        dspy_module: Any = importlib.import_module("dspy")
        signature = type(
            "RerankEvidenceSignature",
            (dspy_module.Signature,),
            {
                "__doc__": "Rank candidate evidence IDs by relevance to the query.",
                "query": dspy_module.InputField(),
                "candidates": dspy_module.InputField(
                    desc="JSON list of objects with id, text, and score"
                ),
                "ranked_ids": dspy_module.OutputField(
                    desc="JSON array of candidate IDs in best-first order"
                ),
            },
        )
        return dspy_module.Predict(signature)


def build_reranker(
    *,
    enable_hf: bool = False,
    enable_dspy: bool = False,
) -> Reranker[T]:
    """Build the strongest configured reranker with safe fallback behavior."""

    if enable_hf:
        try:
            return CrossEncoderReranker()
        except Exception:
            return SimilarityReranker()
    if enable_dspy:
        try:
            return DSPyReranker()
        except ImportError:
            return SimilarityReranker()
    return SimilarityReranker()


def _candidate_text(item: object) -> str:
    text = getattr(item, "text", None)
    return boundary_text(text if text is not None else item, "rerank_candidate_text_failed")


def _candidate_id(item: object) -> str:
    item_id = getattr(item, "id", None)
    return boundary_text(item_id if item_id is not None else item, "rerank_candidate_id_failed")
