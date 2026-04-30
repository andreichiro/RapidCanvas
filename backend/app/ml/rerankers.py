"""Rerankers for retrieved evidence candidates."""

from __future__ import annotations

import importlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

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
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)[:limit]


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

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate[T]],
        limit: int,
    ) -> list[RerankCandidate[T]]:
        """Score query/text pairs with a cross-encoder."""

        pairs = [(query, _candidate_text(candidate.item)) for candidate in candidates]
        model: Any = self._model
        scores = [float(score) for score in model.predict(pairs)]
        rescored = [
            RerankCandidate(item=candidate.item, score=score)
            for candidate, score in zip(candidates, scores, strict=True)
        ]
        return sorted(rescored, key=lambda candidate: candidate.score, reverse=True)[:limit]


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
                query=query,
                candidates=json.dumps(candidate_payload, ensure_ascii=True),
            )
            ranked_ids = json.loads(str(getattr(prediction, "ranked_ids", "[]")))
        except Exception:
            return self._fallback.rerank(query, candidates, limit)

        by_id = {_candidate_id(candidate.item): candidate for candidate in candidates}
        ranked: list[RerankCandidate[T]] = []
        for candidate_id in ranked_ids:
            candidate = by_id.get(str(candidate_id))
            if candidate is not None and candidate not in ranked:
                ranked.append(candidate)
        ranked.extend(candidate for candidate in candidates if candidate not in ranked)
        return ranked[:limit]

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
    return str(text if text is not None else item)


def _candidate_id(item: object) -> str:
    item_id = getattr(item, "id", None)
    return str(item_id if item_id is not None else item)
