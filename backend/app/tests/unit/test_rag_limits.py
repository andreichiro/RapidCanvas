from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, cast

from app.ml.diagnostics import generate_search_queries
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import CrossEncoderReranker, DSPyReranker, RerankCandidate, SimilarityReranker
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService, chunk_document
from app.schemas.domain import ContextDocument, PostContext


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0, 0.0]) for text in texts]


class RaisingEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        raise AssertionError(f"embedding should not be called for {texts!r}")


class EmptyEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        return []


class CountingCrossEncoder:
    calls = 0

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        self.calls += 1
        return [1.0 for _ in pairs]


class CountingPredictor:
    calls = 0

    def __call__(self, **kwargs: object) -> object:
        self.calls += 1
        return type("Prediction", (), {"ranked_ids": "[]"})()


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("bad string")


class BadLimit:
    def __int__(self) -> int:
        raise RuntimeError("bad limit")


class BadCandidate:
    id = BadString()
    text = BadString()


class BadDocumentIterable:
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("documents failed")


def _document() -> ContextDocument:
    return ContextDocument(
        id="D1",
        source_type="web",
        title="Doc",
        url="https://example.com",
        text="Mars rover context.",
        metadata={},
    )


def test_generate_search_queries_clamps_negative_max_queries() -> None:
    post = cast(PostContext, cast(Any, object()))

    assert generate_search_queries(post, supplied_queries=["mars", "rover"], max_queries=-1) == []


def test_generate_search_queries_treats_bad_max_queries_as_zero() -> None:
    post = cast(PostContext, cast(Any, object()))

    assert (
        generate_search_queries(
            post,
            supplied_queries=["mars", "rover"],
            max_queries=cast(Any, BadLimit()),
        )
        == []
    )


def test_rag_service_clamps_negative_retrieval_limits() -> None:
    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=-1,
        evidence_limit=-1,
    )

    assert service.retrieve("mars", [_document()]) == []


def test_rag_service_treats_bad_retrieval_limits_as_zero() -> None:
    service = RagService(
        embedding_provider=RaisingEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=cast(Any, BadLimit()),
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []


def test_zero_retrieval_limit_skips_embedding_work() -> None:
    service = RagService(
        embedding_provider=RaisingEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=0,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []


def test_in_memory_vector_store_clamps_non_positive_query_limit() -> None:
    store = InMemoryVectorStore()

    assert store.query("test", [1.0, 0.0], limit=-1) == []
    assert store.query("test", [1.0, 0.0], limit=0) == []


def test_in_memory_vector_store_treats_bad_query_limit_as_zero() -> None:
    assert InMemoryVectorStore().query("test", [1.0, 0.0], limit=cast(Any, BadLimit())) == []


def test_direct_model_rerankers_skip_work_for_zero_limit() -> None:
    candidate = RerankCandidate(item=_document(), score=0.5)
    cross_model = CountingCrossEncoder()
    predictor = CountingPredictor()

    assert (
        CrossEncoderReranker[ContextDocument](model=cross_model).rerank(
            "mars", [candidate], limit=0
        )
        == []
    )
    assert (
        DSPyReranker[ContextDocument](predictor=predictor).rerank("mars", [candidate], limit=0)
        == []
    )
    assert cross_model.calls == 0
    assert predictor.calls == 0


def test_direct_model_rerankers_skip_work_for_bad_limit() -> None:
    candidate = RerankCandidate(item=_document(), score=0.5)
    cross_model = CountingCrossEncoder()
    predictor = CountingPredictor()

    assert (
        CrossEncoderReranker[ContextDocument](model=cross_model).rerank(
            "mars", [candidate], limit=cast(Any, BadLimit())
        )
        == []
    )
    assert (
        DSPyReranker[ContextDocument](predictor=predictor).rerank(
            "mars", [candidate], limit=cast(Any, BadLimit())
        )
        == []
    )
    assert (
        SimilarityReranker[ContextDocument]().rerank(
            "mars", [candidate], limit=cast(Any, BadLimit())
        )
        == []
    )
    assert cross_model.calls == 0
    assert predictor.calls == 0


def test_direct_model_rerankers_skip_work_for_empty_candidates() -> None:
    cross_model = CountingCrossEncoder()
    predictor = CountingPredictor()

    assert (
        CrossEncoderReranker[ContextDocument](model=cross_model).rerank("mars", [], limit=5) == []
    )
    assert DSPyReranker[ContextDocument](predictor=predictor).rerank("mars", [], limit=5) == []
    assert cross_model.calls == 0
    assert predictor.calls == 0


def test_direct_model_rerankers_degrade_bad_boundary_text() -> None:
    class CapturingCrossEncoder:
        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            assert pairs == [
                (
                    "rerank_query_text_failed:RuntimeError",
                    "rerank_candidate_text_failed:RuntimeError",
                )
            ]
            return [0.75]

    class CapturingPredictor:
        def __call__(self, **kwargs: object) -> object:
            assert kwargs["query"] == "rerank_query_text_failed:RuntimeError"
            payload = json.loads(cast(str, kwargs["candidates"]))
            assert payload[0]["id"] == "rerank_candidate_id_failed:RuntimeError"
            assert payload[0]["text"] == "rerank_candidate_text_failed:RuntimeError"
            return type(
                "Prediction",
                (),
                {"ranked_ids": json.dumps(["rerank_candidate_id_failed:RuntimeError"])},
            )()

    candidate: RerankCandidate[object] = RerankCandidate(item=BadCandidate(), score=0.1)

    cross_ranked = CrossEncoderReranker[object](model=CapturingCrossEncoder()).rerank(
        cast(str, BadString()), [candidate], limit=1
    )
    dspy_ranked = DSPyReranker[object](predictor=CapturingPredictor()).rerank(
        cast(str, BadString()), [candidate], limit=1
    )

    assert cross_ranked[0].score == 0.75
    assert dspy_ranked == [candidate]


def test_rag_service_degrades_bad_query_text() -> None:
    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    evidence = service.retrieve(cast(str, BadString()), [_document()])

    assert len(evidence) == 1


def test_rag_service_degrades_bad_document_container() -> None:
    service = RagService(
        embedding_provider=RaisingEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", cast(Any, BadDocumentIterable())) == []
    assert service.last_diagnostics.warnings == (
        "rag_documents_iter_failed:RuntimeError",
        "in_memory_fallback",
    )


def test_rag_service_degrades_empty_embedding_batch() -> None:
    service = RagService(
        embedding_provider=EmptyEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_embedding_shape_invalid" in service.last_diagnostics.warnings


def test_chunk_document_degrades_bad_document_boundary_fields() -> None:
    document = ContextDocument.model_construct(
        id=BadString(),
        source_type=BadString(),
        title=BadString(),
        url=BadString(),
        text="Mars rover context.",
        metadata=["unexpected"],
    )

    chunks = chunk_document(document, config=ChunkingConfig(name="test", size=100, overlap=10))

    assert chunks[0].document_id == "document_id_text_failed:RuntimeError"
    assert chunks[0].metadata["metadata"] == ["unexpected"]
    assert chunks[0].metadata["source_url"] == "source_url_text_failed:RuntimeError"


def test_dspy_reranker_falls_back_when_ranked_ids_shape_is_not_list() -> None:
    class ScalarRankPredictor:
        def __call__(self, **kwargs: object) -> object:
            del kwargs
            return type("Prediction", (), {"ranked_ids": "123"})()

    ranked = DSPyReranker[ContextDocument](predictor=ScalarRankPredictor()).rerank(
        "query",
        [
            RerankCandidate(item=_document(), score=0.1),
            RerankCandidate(item=_document().model_copy(update={"id": "D2"}), score=0.9),
        ],
        limit=2,
    )

    assert [candidate.item.id for candidate in ranked] == ["D2", "D1"]
