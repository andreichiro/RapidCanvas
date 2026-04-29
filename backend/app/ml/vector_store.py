"""Chunking, vector storage, and retrieval service for cited evidence."""

from __future__ import annotations

import importlib
import math
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from app.guardrails.prompt_injection import PromptInjectionScanner, sanitize_context_documents
from app.ml.diagnostics import RetrievalDiagnostics, retrieval_diagnostics
from app.ml.embeddings import EmbeddingProvider, text_hash
from app.ml.rerankers import RerankCandidate, Reranker, SimilarityReranker
from app.schemas.domain import ContextDocument, Evidence


@dataclass(frozen=True)
class ChunkingConfig:
    """Chunk size and overlap configuration."""

    name: str
    size: int
    overlap: int

    def validate(self) -> None:
        """Validate that chunk boundaries can make progress."""

        if self.size <= 0:
            raise ValueError("chunk size must be positive")
        if self.overlap < 0:
            raise ValueError("chunk overlap cannot be negative")
        if self.overlap >= self.size:
            raise ValueError("chunk overlap must be smaller than chunk size")


CHUNKING_VARIANTS: tuple[ChunkingConfig, ...] = (
    ChunkingConfig(name="small_500_100", size=500, overlap=100),
    ChunkingConfig(name="medium_700_100", size=700, overlap=100),
    ChunkingConfig(name="large_900_150", size=900, overlap=150),
)
DEFAULT_CHUNKING_CONFIG = CHUNKING_VARIANTS[1]


@dataclass(frozen=True)
class DocumentChunk:
    """A retrievable text span tied back to its source document."""

    id: str
    document_id: str
    source_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorSearchResult:
    """One vector search hit."""

    chunk: DocumentChunk
    score: float


class VectorStore(Protocol):
    """Vector store boundary used by RagService."""

    def recreate_collection(self, vector_size: int) -> None:
        """Create or reset storage for the current retrieval pass."""

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[list[float]]) -> None:
        """Insert chunk vectors."""

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
        """Return nearest chunks."""


class InMemoryVectorStore:
    """Deterministic vector store for tests and local fallback."""

    def __init__(self) -> None:
        self._items: list[tuple[DocumentChunk, list[float]]] = []

    def recreate_collection(self, vector_size: int) -> None:
        del vector_size
        self._items = []

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[list[float]]) -> None:
        self._items.extend(
            (chunk, embedding)
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
        results = [
            VectorSearchResult(chunk=chunk, score=_cosine_01(embedding, stored_embedding))
            for chunk, stored_embedding in self._items
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:limit]


class QdrantVectorStore:
    """Qdrant local-mode vector store."""

    def __init__(
        self,
        *,
        path: str | Path = ".cache/qdrant",
        collection_name: str = "rapidcanvas_context",
        client: Any | None = None,
    ) -> None:
        self._collection_name = collection_name
        if client is not None:
            self._client = client
        else:
            qdrant_client = importlib.import_module("qdrant_client")
            self._client = qdrant_client.QdrantClient(path=str(path))

    def recreate_collection(self, vector_size: int) -> None:
        models = importlib.import_module("qdrant_client.models")
        with suppress(Exception):
            self._client.delete_collection(collection_name=self._collection_name)
        self._client.create_collection(
            collection_name=self._collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[list[float]]) -> None:
        models = importlib.import_module("qdrant_client.models")
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.id)),
                vector=embedding,
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "source_id": chunk.source_id,
                    "text": chunk.text,
                    "metadata": chunk.metadata,
                },
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        self._client.upsert(collection_name=self._collection_name, points=points)

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
        if hasattr(self._client, "query_points"):
            response = self._client.query_points(
                collection_name=self._collection_name,
                query=embedding,
                limit=limit,
            )
            points = response.points
        else:
            points = self._client.search(
                collection_name=self._collection_name,
                query_vector=embedding,
                limit=limit,
            )
        return [_point_to_result(point) for point in points]


class RagService:
    """Chunk, embed, retrieve, rerank, and return cited evidence."""

    def __init__(
        self,
        *,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore | None = None,
        reranker: Reranker[DocumentChunk] | None = None,
        chunking: ChunkingConfig = DEFAULT_CHUNKING_CONFIG,
        scanner: PromptInjectionScanner | None = None,
        retrieve_limit: int = 30,
        evidence_limit: int = 6,
    ) -> None:
        self._embedding_provider = embedding_provider
        self._vector_store = vector_store or InMemoryVectorStore()
        self._reranker = reranker or SimilarityReranker()
        self._chunking = chunking
        self._scanner = scanner or PromptInjectionScanner()
        self._retrieve_limit = retrieve_limit
        self._evidence_limit = evidence_limit
        self._last_diagnostics = RetrievalDiagnostics()

    @property
    def last_diagnostics(self) -> RetrievalDiagnostics:
        """Return warnings and guardrail flags from the previous retrieval pass."""

        return self._last_diagnostics

    def retrieve(self, query: str, documents: list[ContextDocument]) -> list[Evidence]:
        """Return top evidence chunks for a query and source documents."""

        self._last_diagnostics = RetrievalDiagnostics()
        if not query.strip() or not documents:
            return []
        sanitized_documents, scans = sanitize_context_documents(documents, scanner=self._scanner)
        self._last_diagnostics = retrieval_diagnostics(sanitized_documents, scans)
        chunks = chunk_documents(sanitized_documents, config=self._chunking)
        if not chunks:
            return []
        chunk_embeddings = self._embedding_provider.embed([chunk.text for chunk in chunks])
        vector_size = len(chunk_embeddings[0])
        self._vector_store.recreate_collection(vector_size=vector_size)
        self._vector_store.upsert(chunks, chunk_embeddings)
        query_embedding = self._embedding_provider.embed([query])[0]
        search_results = self._vector_store.query(
            query_embedding,
            limit=min(self._retrieve_limit, len(chunks)),
        )
        candidates = [
            RerankCandidate(item=result.chunk, score=result.score)
            for result in search_results
        ]
        ranked = self._reranker.rerank(query, candidates, limit=self._evidence_limit)
        return [
            Evidence(
                id=f"E{index}",
                document_id=candidate.item.document_id,
                text=candidate.item.text,
                score=max(0.0, float(candidate.score)),
                source_id=candidate.item.source_id,
            )
            for index, candidate in enumerate(ranked, start=1)
        ]


def chunk_document(
    document: ContextDocument,
    config: ChunkingConfig = DEFAULT_CHUNKING_CONFIG,
) -> list[DocumentChunk]:
    """Split a document into overlapping character chunks."""

    config.validate()
    text = document.text.strip()
    if not text:
        return []
    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + config.size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunk_id = (
                f"{document.id}:{index}:"
                f"{text_hash(f'{config.name}:{start}:{end}:{chunk_text}')[:16]}"
            )
            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    document_id=document.id,
                    source_id=document.id,
                    text=chunk_text,
                    metadata={
                        **document.metadata,
                        "chunk_index": index,
                        "chunk_start": start,
                        "chunk_end": end,
                        "chunking": config.name,
                        "source_url": document.url,
                        "source_type": document.source_type,
                        "source_title": document.title,
                    },
                )
            )
            index += 1
        if end >= len(text):
            break
        start = end - config.overlap
    return chunks


def chunk_documents(
    documents: list[ContextDocument],
    config: ChunkingConfig = DEFAULT_CHUNKING_CONFIG,
) -> list[DocumentChunk]:
    """Chunk a document batch."""

    chunks: list[DocumentChunk] = []
    for document in documents:
        chunks.extend(chunk_document(document, config=config))
    return chunks


def _cosine_01(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    cosine = dot / (left_norm * right_norm)
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def _point_to_result(point: Any) -> VectorSearchResult:
    payload = getattr(point, "payload", {}) or {}
    chunk = DocumentChunk(
        id=str(payload.get("chunk_id", "")),
        document_id=str(payload.get("document_id", "")),
        source_id=str(payload.get("source_id", "")),
        text=str(payload.get("text", "")),
        metadata=dict(payload.get("metadata", {}) or {}),
    )
    return VectorSearchResult(chunk=chunk, score=max(0.0, float(getattr(point, "score", 0.0))))
