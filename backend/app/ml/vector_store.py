"""Chunking, vector storage, and retrieval service for cited evidence."""

from __future__ import annotations

import importlib
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from app.guardrails.prompt_injection import PromptInjectionScanner, sanitize_context_documents
from app.ml import rag_runtime as rr
from app.ml.boundary import boundary_attr, boundary_text, bounded_items, safe_limit
from app.ml.c2_policy import unique_documents_by_id
from app.ml.diagnostics import RetrievalDiagnostics, retrieval_diagnostics
from app.ml.embeddings import EmbeddingProvider, text_hash
from app.ml.rag_boundary import RetrievalDiagnosticsState
from app.ml.rerankers import Reranker, SimilarityReranker
from app.ml.vector_payloads import (
    chunk_metadata,
    cosine_01,
    metadata_mapping,
    payload_mapping,
    payload_value,
    public_score,
    qdrant_payload,
    qdrant_point_id,
)
from app.schemas.domain import ContextDocument, Evidence


@dataclass(frozen=True)
class ChunkingConfig:
    name: str
    size: int
    overlap: int

    def validate(self) -> None:
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
    id: str
    document_id: str
    source_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorSearchResult:
    chunk: DocumentChunk
    score: float


class VectorStore(Protocol):
    def recreate_collection(self, vector_size: int) -> None: ...

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[list[float]]) -> None:
        ...

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]: ...


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._items: list[tuple[DocumentChunk, list[float]]] = []

    def recreate_collection(self, vector_size: int) -> None:
        self._items = []

    def upsert(self, chunks: Sequence[DocumentChunk], embeddings: Sequence[list[float]]) -> None:
        self._items.extend(
            (chunk, embedding)
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        )

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
        limit_value = safe_limit(limit)
        if limit_value == 0:
            return []
        results = [
            VectorSearchResult(chunk=chunk, score=cosine_01(embedding, stored_embedding))
            for chunk, stored_embedding in self._items
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:limit_value]


class QdrantVectorStore:
    def __init__(
        self,
        *,
        url: str | None = None,
        path: str | Path = ".cache/qdrant",
        collection_name: str = "rapidcanvas_context",
        client: Any | None = None,
    ) -> None:
        self._collection_name = collection_name
        if client is not None:
            self._client = client
        else:
            qdrant_client = importlib.import_module("qdrant_client")
            client_kwargs = {"url": url} if url else {"path": str(path)}
            self._client = qdrant_client.QdrantClient(**client_kwargs)

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
                id=qdrant_point_id(chunk),
                vector=embedding,
                payload=qdrant_payload(chunk),
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        self._client.upsert(collection_name=self._collection_name, points=points)

    def query(self, embedding: list[float], limit: int) -> list[VectorSearchResult]:
        limit_value = safe_limit(limit)
        if limit_value == 0:
            return []
        if hasattr(self._client, "query_points"):
            response = self._client.query_points(
                collection_name=self._collection_name,
                query=embedding,
                limit=limit_value,
            )
            points = response.points
        else:
            points = self._client.search(
                collection_name=self._collection_name,
                query_vector=embedding,
                limit=limit_value,
            )
        return [_point_to_result(point) for point in points]


class RagService:
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
        self._retrieve_limit = safe_limit(retrieve_limit)
        self._evidence_limit = safe_limit(evidence_limit)
        self._diagnostics_state = RetrievalDiagnosticsState()
        self._lock = RLock()

    @property
    def last_diagnostics(self) -> RetrievalDiagnostics:
        return self._diagnostics_state.get()

    def retrieve(self, query: str, documents: list[ContextDocument]) -> list[Evidence]:
        with self._lock:
            return self._retrieve_locked(query, documents)

    def _retrieve_locked(self, query: str, documents: list[ContextDocument]) -> list[Evidence]:
        self._record_diagnostics(RetrievalDiagnostics())
        query_text = boundary_text(query, "rag_query_text_failed")
        document_items, document_warnings = bounded_items(
            documents, 200, "rag_documents_iter_failed")
        documents = [doc for doc in document_items if isinstance(doc, ContextDocument)]
        if invalid_count := len(document_items) - len(documents):
            document_warnings.append(f"rag_documents_invalid:{invalid_count}")
        if not query_text.strip() or not documents:
            self._record_diagnostics(RetrievalDiagnostics(warnings=tuple(document_warnings)))
            return []
        sanitized_documents, scans = sanitize_context_documents(documents, scanner=self._scanner)
        sanitized_documents = unique_documents_by_id(sanitized_documents)
        document_ids = {document.id for document in sanitized_documents}
        diagnostics = retrieval_diagnostics(sanitized_documents, scans)
        self._record_diagnostics(
            RetrievalDiagnostics(
                prompt_injection_flags=diagnostics.prompt_injection_flags,
                warnings=tuple([*document_warnings, *diagnostics.warnings]),
            )
        )
        if self._retrieve_limit <= 0 or self._evidence_limit <= 0:
            return []
        chunks = chunk_documents(sanitized_documents, config=self._chunking)
        if not chunks:
            return []
        ranked, runtime_warnings = rr.ranked_rag_candidates(
            query_text=query_text,
            chunks=chunks,
            embedding_provider=self._embedding_provider,
            vector_store=self._vector_store,
            reranker=self._reranker,
            retrieve_limit=self._retrieve_limit,
            evidence_limit=self._evidence_limit,
        )
        if runtime_warnings:
            current_diagnostics = self.last_diagnostics
            self._record_diagnostics(
                RetrievalDiagnostics(
                    prompt_injection_flags=current_diagnostics.prompt_injection_flags,
                    warnings=(*current_diagnostics.warnings, *runtime_warnings),
                )
            )
            if not ranked:
                return []
        rag_evidence = rr.evidence_from_ranked_candidates(ranked, document_ids)
        evidence, evidence_warnings, reranker_scores = rag_evidence
        current_diagnostics = self.last_diagnostics
        self._record_diagnostics(
            RetrievalDiagnostics(
                prompt_injection_flags=current_diagnostics.prompt_injection_flags,
                warnings=(*current_diagnostics.warnings, *evidence_warnings),
                reranker_scores=reranker_scores,
            )
        )
        return evidence

    def _record_diagnostics(self, diagnostics: RetrievalDiagnostics) -> None:
        self._diagnostics_state.set(diagnostics)


def chunk_document(
    document: ContextDocument,
    config: ChunkingConfig = DEFAULT_CHUNKING_CONFIG,
) -> list[DocumentChunk]:
    """Split a document into overlapping character chunks."""

    config.validate()
    text = boundary_text(
        boundary_attr(document, "text", "document_text_field_failed"),
        "document_text_failed",
    ).strip()
    if not text:
        return []
    document_id = boundary_text(
        boundary_attr(document, "id", "document_id_field_failed"),
        "document_id_text_failed",
    ) or "DOC-empty"
    chunks: list[DocumentChunk] = []
    start = 0
    index = 0
    while start < len(text):
        end = min(start + config.size, len(text))
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunk_id = (
                f"{document_id}:{index}:"
                f"{text_hash(f'{config.name}:{start}:{end}:{chunk_text}')[:16]}"
            )
            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    document_id=document_id,
                    source_id=document_id,
                    text=chunk_text,
                    metadata=chunk_metadata(
                        document,
                        chunk_index=index,
                        chunk_start=start,
                        chunk_end=end,
                        chunking=config.name,
                    ),
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
    return [chunk for document in documents for chunk in chunk_document(document, config=config)]


def _point_to_result(point: Any) -> VectorSearchResult:
    payload = payload_mapping(getattr(point, "payload", {}) or {})
    chunk = DocumentChunk(
        id=boundary_text(payload_value(payload, "chunk_id"), "chunk_id_text_failed"),
        document_id=boundary_text(payload_value(payload, "document_id"), "document_id_text_failed"),
        source_id=boundary_text(payload_value(payload, "source_id"), "source_id_text_failed"),
        text=boundary_text(payload_value(payload, "text"), "chunk_text_failed"),
        metadata=metadata_mapping(payload_value(payload, "metadata", None)),
    )
    return VectorSearchResult(chunk=chunk, score=public_score(getattr(point, "score", 0.0)))
