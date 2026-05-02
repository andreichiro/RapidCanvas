from __future__ import annotations

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

        def recreate_collection(self, vector_size: int) -> None:
            del vector_size
            raise RuntimeError("qdrant down")

        def upsert(self, chunks: object, embeddings: object) -> None:
            del chunks, embeddings

        def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
            del embedding, limit
            return []

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
        def recreate_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, chunks: object, embeddings: object) -> None:
            del chunks, embeddings

        def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
            del embedding, limit
            return [VectorSearchResult(chunk=object(), score=1.0)]  # type: ignore[arg-type]

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
        def recreate_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, chunks: object, embeddings: object) -> None:
            del chunks, embeddings

        def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
            del embedding, limit
            return [VectorSearchResult(chunk=WeirdChunk(), score=1.0)]  # type: ignore[arg-type]

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
        def recreate_collection(self, vector_size: int) -> None:
            del vector_size

        def upsert(self, chunks: object, embeddings: object) -> None:
            del chunks, embeddings

        def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
            del embedding, limit
            return [VectorSearchResult(chunk=OrphanChunk(), score=1.0)]  # type: ignore[arg-type]

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
