from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService, VectorSearchResult
from app.schemas.domain import ContextDocument


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0]) for text in texts]


class EmptyEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        del texts
        return []


class QueryEmbeddingFailsProvider:
    def __init__(self) -> None:
        self._calls = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        self._calls += 1
        if self._calls == 1:
            return [normalize_vector([1.0]) for _text in texts]
        return []


def _document() -> ContextDocument:
    return ContextDocument(
        id="D1",
        source_type="web",
        title="Doc",
        url="https://example.com",
        text="Mars rover context.",
        metadata={},
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
    assert "in_memory_fallback" in service.last_diagnostics.warnings


def test_rag_service_does_not_clear_namespace_before_vector_collection_opens() -> None:
    class ClearFailsIfCalledStore(InMemoryVectorStore):
        def clear_namespace(self, namespace: str) -> None:
            del namespace
            raise RuntimeError("namespace was never opened")

    service = RagService(
        embedding_provider=EmptyEmbeddingProvider(),
        vector_store=ClearFailsIfCalledStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_embedding_shape_invalid" in service.last_diagnostics.warnings
    assert all(
        not warning.startswith("rag_namespace_clear_failed")
        for warning in service.last_diagnostics.warnings
    )


def test_rag_service_keeps_clear_warning_after_query_embedding_failure() -> None:
    class ClearFailsStore(InMemoryVectorStore):
        def clear_namespace(self, namespace: str) -> None:
            super().clear_namespace(namespace)
            raise RuntimeError("clear failed")

    service = RagService(
        embedding_provider=QueryEmbeddingFailsProvider(),
        vector_store=ClearFailsStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_query_embedding_shape_invalid" in service.last_diagnostics.warnings
    assert "rag_namespace_clear_failed:RuntimeError" in service.last_diagnostics.warnings


def test_rag_service_records_qdrant_backend_when_vector_store_succeeds() -> None:
    class FakeQdrantStore(InMemoryVectorStore):
        backend_name = "qdrant_vector_store"

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=FakeQdrantStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    evidence = service.retrieve("mars", [_document()])

    assert evidence[0].document_id == "D1"
    assert "qdrant_vector_store" in service.last_diagnostics.warnings


def test_rag_service_retries_in_memory_when_qdrant_runtime_fails() -> None:
    class FailingQdrantStore:
        backend_name = "qdrant_vector_store"

        def ensure_collection(self, vector_size: int) -> None:
            del vector_size
            raise RuntimeError("qdrant down")

        def upsert(self, namespace: str, chunks: object, embeddings: object) -> None:
            del namespace, chunks, embeddings

        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del namespace, embedding, limit
            return []

        def clear_namespace(self, namespace: str) -> None:
            del namespace

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=FailingQdrantStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    evidence = service.retrieve("mars", [_document()])

    assert evidence[0].document_id == "D1"
    assert "qdrant_runtime_failed_using_in_memory_fallback" in service.last_diagnostics.warnings
    assert "in_memory_fallback" in service.last_diagnostics.warnings


def test_rag_service_falls_back_on_malformed_reranker_output() -> None:
    class BadReranker:
        def rerank(self, query: str, candidates: object, limit: int) -> list[object]:
            del query, candidates, limit
            return [object()]

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=cast(Any, BadReranker()),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    evidence = service.retrieve("mars", [_document()])

    assert evidence[0].document_id == "D1"
    assert "rag_reranker_invalid_candidates:1" in service.last_diagnostics.warnings


def test_rag_service_drops_malformed_vector_store_chunks() -> None:
    class BadVectorStore:
        def ensure_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, namespace: str, chunks: object, embeddings: object) -> None:
            del namespace, chunks, embeddings

        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del namespace, embedding, limit
            return [VectorSearchResult(chunk=object(), score=1.0)]  # type: ignore[arg-type]

        def clear_namespace(self, namespace: str) -> None:
            del namespace

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=BadVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_reranker_invalid_candidates:1" in service.last_diagnostics.warnings


def test_rag_service_drops_malformed_vector_chunk_fields() -> None:
    class BadText:
        def __str__(self) -> str:
            raise RuntimeError("bad text")

    class WeirdChunk:
        document_id = BadText()
        source_id = "D1"
        text = "Mars context"

    class WeirdVectorStore:
        def ensure_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, namespace: str, chunks: object, embeddings: object) -> None:
            del namespace, chunks, embeddings

        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del namespace, embedding, limit
            return [VectorSearchResult(chunk=WeirdChunk(), score=1.0)]  # type: ignore[arg-type]

        def clear_namespace(self, namespace: str) -> None:
            del namespace

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=WeirdVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_evidence_invalid_candidate:1" in service.last_diagnostics.warnings


def test_rag_service_drops_orphaned_vector_chunk_fields() -> None:
    class OrphanChunk:
        document_id = "ORPHAN"
        source_id = "ORPHAN"
        text = "Mars context"

    class OrphanVectorStore:
        def ensure_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, namespace: str, chunks: object, embeddings: object) -> None:
            del namespace, chunks, embeddings

        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del namespace, embedding, limit
            return [VectorSearchResult(chunk=OrphanChunk(), score=1.0)]  # type: ignore[arg-type]

        def clear_namespace(self, namespace: str) -> None:
            del namespace

    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=OrphanVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
        retrieve_limit=1,
        evidence_limit=1,
    )

    assert service.retrieve("mars", [_document()]) == []
    assert "rag_evidence_orphaned_candidate:1" in service.last_diagnostics.warnings


def test_rag_service_quality_adjustment_beats_off_topic_vector_score() -> None:
    class FixedOrderStore(InMemoryVectorStore):
        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del embedding, limit
            by_id = {
                chunk.document_id: chunk for chunk, _embedding in self.namespace_items(namespace)
            }
            return [
                VectorSearchResult(chunk=by_id["BAD"], score=1.0),
                VectorSearchResult(chunk=by_id["GOOD"], score=0.35),
            ]

    good = ContextDocument(
        id="GOOD",
        source_type="web",
        title="Official Python 3.13 release notes",
        url="https://docs.python.org/3.13/whatsnew/3.13.html",
        text="Python 3.13 release notes explain CPython JIT build configuration.",
        metadata={"source_quality_score": 0.95},
    )
    bad = ContextDocument(
        id="BAD",
        source_type="web",
        title="Python JIT trading card catalog",
        url="https://cards.example/python-jit-card",
        text="Python 3.13 CPython JIT build configuration trading card marketplace coupon.",
        metadata={"source_quality_score": 0.2},
    )
    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=FixedOrderStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=200, overlap=20),
        retrieve_limit=2,
        evidence_limit=2,
    )

    evidence = service.retrieve("Python 3.13 JIT", [good, bad])

    assert [item.document_id for item in evidence] == ["GOOD", "BAD"]
    assert evidence[0].score > evidence[1].score


def test_rag_service_combines_vector_reranker_quality_and_channel_scores() -> None:
    class FixedOrderStore(InMemoryVectorStore):
        def query(
            self, namespace: str, embedding: list[float], limit: int
        ) -> list[VectorSearchResult]:
            del embedding, limit
            by_id = {
                chunk.document_id: chunk for chunk, _embedding in self.namespace_items(namespace)
            }
            return [
                VectorSearchResult(chunk=by_id["VECTOR"], score=0.95),
                VectorSearchResult(chunk=by_id["BALANCED"], score=0.55),
            ]

    class FixedReranker:
        def rerank(self, query: str, candidates: Sequence[Any], limit: int) -> list[object]:
            del query, limit
            by_id = {candidate.item.document_id: candidate for candidate in candidates}
            return [
                by_id["VECTOR"].__class__(item=by_id["VECTOR"].item, score=0.95),
                by_id["BALANCED"].__class__(item=by_id["BALANCED"].item, score=0.45),
            ]

    vector_only = ContextDocument(
        id="VECTOR",
        source_type="web",
        title="Keyword-stuffed marketplace page",
        url="https://cards.example/vector",
        text="Python 3.13 JIT CPython build configuration marketplace catalog coupon.",
        metadata={"source_quality_score": 0.1},
    )
    balanced = ContextDocument(
        id="BALANCED",
        source_type="web",
        title="Official Python 3.13 release notes",
        url="https://docs.python.org/3.13/whatsnew/3.13.html",
        text="Python 3.13 release notes explain CPython JIT build configuration.",
        metadata={"source_quality_score": 0.96},
    )
    service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=FixedOrderStore(),
        reranker=cast(Any, FixedReranker()),
        chunking=ChunkingConfig(name="test", size=200, overlap=20),
        retrieve_limit=2,
        evidence_limit=2,
    )

    evidence = service.retrieve("Python 3.13 JIT", [vector_only, balanced])

    assert [item.document_id for item in evidence] == ["BALANCED", "VECTOR"]
    assert evidence[0].score > evidence[1].score
