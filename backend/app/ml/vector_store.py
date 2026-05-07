"""Chunking, vector storage, and retrieval service for cited evidence."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from app.guardrails.prompt_injection import (
    PromptInjectionScanner,
    PromptInjectionScanResult,
    sanitize_context_documents,
)
from app.ml import rag_runtime as rr
from app.ml.boundary import boundary_attr, boundary_text, bounded_items, safe_limit
from app.ml.c2_policy import unique_documents_by_id
from app.ml.diagnostics import (
    RetrievalDiagnostics,
    diagnostic_warnings,
    retrieval_diagnostics,
    vector_store_backend_name,
)
from app.ml.embeddings import EmbeddingProvider, text_hash
from app.ml.rag_boundary import RetrievalDiagnosticsState
from app.ml.rerankers import RerankCandidate, Reranker, SimilarityReranker
from app.ml.vector_backends import (
    DocumentChunk,
    InMemoryVectorStore,
    QdrantVectorStore,
    VectorSearchResult,
    VectorStore,
)
from app.ml.vector_payloads import chunk_metadata
from app.schemas.domain import ContextDocument, Evidence

__all__ = [
    "CHUNKING_VARIANTS",
    "DEFAULT_CHUNKING_CONFIG",
    "ChunkingConfig",
    "DocumentChunk",
    "InMemoryVectorStore",
    "QdrantVectorStore",
    "RagService",
    "VectorSearchResult",
    "VectorStore",
    "chunk_document",
    "chunk_documents",
    "retrieval_namespace",
]


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


@dataclass(frozen=True)
class _RetrievalInputs:
    query_text: str
    documents: list[ContextDocument]
    warnings: list[str]
    vector_store_backend: str


CHUNKING_VARIANTS: tuple[ChunkingConfig, ...] = (
    ChunkingConfig(name="small_500_100", size=500, overlap=100),
    ChunkingConfig(name="medium_700_100", size=700, overlap=100),
    ChunkingConfig(name="large_900_150", size=900, overlap=150),
)
DEFAULT_CHUNKING_CONFIG = CHUNKING_VARIANTS[1]


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

    @property
    def last_diagnostics(self) -> RetrievalDiagnostics:
        return self._diagnostics_state.get()

    def retrieve(
        self,
        query: str,
        documents: list[ContextDocument],
        *,
        namespace: str | None = None,
    ) -> list[Evidence]:
        retrieval_inputs = self._prepare_retrieval_inputs(query, documents)
        if not retrieval_inputs.query_text.strip() or not retrieval_inputs.documents:
            self._record_warning_diagnostics(
                retrieval_inputs.warnings,
                retrieval_inputs.vector_store_backend,
            )
            return []
        sanitized_documents, scans = sanitize_context_documents(
            retrieval_inputs.documents, scanner=self._scanner
        )
        sanitized_documents = unique_documents_by_id(sanitized_documents)
        document_ids = {document.id for document in sanitized_documents}
        self._record_input_diagnostics(
            sanitized_documents,
            scans,
            retrieval_inputs.warnings,
            retrieval_inputs.vector_store_backend,
        )
        if self._retrieve_limit <= 0 or self._evidence_limit <= 0:
            return []
        chunks = chunk_documents(sanitized_documents, config=self._chunking)
        if not chunks:
            return []
        ranked, runtime_warnings, vector_store_backend = self._ranked_candidates(
            retrieval_inputs.query_text,
            chunks,
            retrieval_inputs.vector_store_backend,
            namespace=namespace
            or retrieval_namespace(retrieval_inputs.query_text, sanitized_documents),
        )
        if runtime_warnings:
            self._record_warning_diagnostics(runtime_warnings, vector_store_backend)
            if not ranked:
                return []
        rag_evidence = rr.evidence_from_ranked_candidates(ranked, document_ids)
        evidence, evidence_warnings, reranker_scores = rag_evidence
        current_diagnostics = self.last_diagnostics
        self._record_diagnostics(
            RetrievalDiagnostics(
                prompt_injection_flags=current_diagnostics.prompt_injection_flags,
                warnings=tuple(
                    diagnostic_warnings(
                        [*current_diagnostics.warnings, *evidence_warnings],
                        vector_store_backend,
                    )
                ),
                reranker_scores=reranker_scores,
            )
        )
        return evidence

    def _prepare_retrieval_inputs(
        self,
        query: str,
        documents: list[ContextDocument],
    ) -> _RetrievalInputs:
        self._record_diagnostics(RetrievalDiagnostics())
        vector_store_backend = vector_store_backend_name(self._vector_store)
        query_text = boundary_text(query, "rag_query_text_failed")
        document_items, document_warnings = bounded_items(
            documents, 200, "rag_documents_iter_failed"
        )
        safe_documents = [doc for doc in document_items if isinstance(doc, ContextDocument)]
        if invalid_count := len(document_items) - len(safe_documents):
            document_warnings.append(f"rag_documents_invalid:{invalid_count}")
        return _RetrievalInputs(
            query_text=query_text,
            documents=safe_documents,
            warnings=document_warnings,
            vector_store_backend=vector_store_backend,
        )

    def _record_input_diagnostics(
        self,
        documents: list[ContextDocument],
        scans: Sequence[PromptInjectionScanResult],
        warnings: Sequence[str],
        vector_store_backend: str,
    ) -> None:
        diagnostics = retrieval_diagnostics(documents, scans)
        self._record_diagnostics(
            RetrievalDiagnostics(
                prompt_injection_flags=diagnostics.prompt_injection_flags,
                warnings=tuple(
                    diagnostic_warnings(
                        [*warnings, *diagnostics.warnings],
                        vector_store_backend,
                    )
                ),
            )
        )

    def _ranked_candidates(
        self,
        query_text: str,
        chunks: list[DocumentChunk],
        vector_store_backend: str,
        *,
        namespace: str,
    ) -> tuple[list[RerankCandidate[DocumentChunk]], list[str], str]:
        ranked, runtime_warnings = self._ranked_with_store(
            query_text, chunks, self._vector_store, namespace=namespace
        )
        if runtime_warnings and not ranked and vector_store_backend == "qdrant_vector_store":
            fallback_ranked, fallback_warnings = self._ranked_with_store(
                query_text, chunks, InMemoryVectorStore(), namespace=namespace
            )
            if fallback_ranked:
                return (
                    fallback_ranked,
                    [
                        *runtime_warnings,
                        "qdrant_runtime_failed_using_in_memory_fallback",
                        *fallback_warnings,
                    ],
                    "in_memory_fallback",
                )
        return ranked, runtime_warnings, vector_store_backend

    def _ranked_with_store(
        self,
        query_text: str,
        chunks: list[DocumentChunk],
        vector_store: VectorStore,
        *,
        namespace: str,
    ) -> tuple[list[RerankCandidate[DocumentChunk]], list[str]]:
        return rr.ranked_rag_candidates(
            query_text=query_text,
            chunks=chunks,
            namespace=namespace,
            embedding_provider=self._embedding_provider,
            vector_store=vector_store,
            reranker=self._reranker,
            retrieve_limit=self._retrieve_limit,
            evidence_limit=self._evidence_limit,
        )

    def _record_warning_diagnostics(
        self,
        warnings: Sequence[str],
        vector_store_backend: str,
    ) -> None:
        current = self.last_diagnostics
        self._record_diagnostics(
            RetrievalDiagnostics(
                prompt_injection_flags=current.prompt_injection_flags,
                warnings=tuple(
                    diagnostic_warnings([*current.warnings, *warnings], vector_store_backend)
                ),
            )
        )

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
    document_id = (
        boundary_text(
            boundary_attr(document, "id", "document_id_field_failed"),
            "document_id_text_failed",
        )
        or "DOC-empty"
    )
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


def retrieval_namespace(
    query: str,
    documents: Sequence[ContextDocument],
    *,
    request_key: object = "",
) -> str:
    document_fingerprint = "|".join(document.id for document in documents[:20])
    request_fingerprint = boundary_text(request_key, "request_namespace_key_failed")
    stable_part = text_hash(f"{request_fingerprint}|{query}|{document_fingerprint}")[:12]
    return f"retrieval-{stable_part}-{uuid4().hex[:12]}"
