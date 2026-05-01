from __future__ import annotations

from typing import Any, cast

import pytest

from app.ml.diagnostics import make_retrieval_result
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, Evidence, PostContext


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0]) for text in texts]


class MissingFieldProvider:
    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        del query, limit
        return [
            ContextDocument.model_construct(
                source_type="web",
                title="Missing URL and ID",
                text="Mars context.",
                metadata={},
            )
        ]


def _service(**settings: object) -> RetrievalService:
    return RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
            chunking=ChunkingConfig(name="test", size=100, overlap=10),
        ),
        search_providers=[cast(Any, MissingFieldProvider())],
        settings=RetrievalSettings(**cast(Any, settings)),
    )


@pytest.mark.asyncio
async def test_missing_post_context_fields_degrade_to_c2_warnings() -> None:
    result = await _service(
        include_search=False,
        include_linked_pages=False,
    ).retrieve(PostContext.model_construct(), queries=[])

    assert result.documents == []
    assert "retrieval_no_documents" in result.warnings
    assert any(
        warning.startswith("blocked_document_url:POST-target")
        for warning in result.warnings
    )
    assert "private_url_blocked" in result.guardrail_flags


@pytest.mark.asyncio
async def test_empty_post_context_urls_degrade_to_source_block_evidence() -> None:
    result = await _service(
        include_search=False,
        include_linked_pages=False,
    ).retrieve(PostContext.model_construct(url=None, text="Mars", images=[{"alt_text": "Alt"}]))

    assert "private_url_blocked" in result.guardrail_flags
    assert any("blocked_unsupported_scheme:about" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_missing_provider_document_fields_are_blocked_not_crashing() -> None:
    result = await _service(
        include_thread_context=False,
        include_linked_pages=False,
    ).retrieve(PostContext.model_construct(text="Mars"), queries=["mars"])

    assert result.documents == []
    assert "retrieval_no_documents" in result.warnings
    assert any(warning.startswith("blocked_document_url:") for warning in result.warnings)
    assert "private_url_blocked" in result.guardrail_flags


def test_missing_evidence_fields_degrade_at_c2_boundary() -> None:
    result = make_retrieval_result(
        documents=[
            ContextDocument(
                id="D1",
                source_type="web",
                title="Doc",
                url="https://example.com",
                text="Mars context.",
            )
        ],
        evidence=[
            Evidence.model_construct(
                document_id="D1", source_id="D1", text="Mars context.", score=1.0
            )
        ],
        queries=[],
        prompt_flags=[],
        warnings=[],
        private_url_blocks=[],
    )

    assert len(result.evidence) == 1
    assert result.evidence[0].id == "evidence_id_field_failed:AttributeError"
    assert result.evidence[0].model_dump(mode="json")
