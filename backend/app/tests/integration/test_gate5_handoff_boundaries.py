from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.ml.diagnostics import RetrievalDiagnostics
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, Evidence, PostContext


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0]) for text in texts]


class ExplodingIterable:
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("iterator setup failed")


class ExplodingAfterFirst:
    def __iter__(self) -> Iterator[str]:
        yield "http://127.0.0.1/one"
        raise RuntimeError("iterator failed")


class BadCreatedAt:
    def __getattribute__(self, name: str) -> object:
        if name == "isoformat":
            raise RuntimeError("created_at failed")
        return object.__getattribute__(self, name)


class BadDiagnosticsRagService:
    @property
    def last_diagnostics(self) -> RetrievalDiagnostics:
        raise RuntimeError("diagnostics failed")

    def retrieve(self, query: str, documents: list[ContextDocument]) -> list[Evidence]:
        del query
        return [
            Evidence(
                id="E1",
                document_id=documents[0].id,
                text=documents[0].text,
                score=0.7,
                source_id=documents[0].id,
            )
        ]


def _post(**overrides: object) -> PostContext:
    fields: dict[str, object] = {
        "url": "https://bsky.app/profile/science.example/post/3kfixture",
        "at_uri": "at://did:plc:science/app.bsky.feed.post/3kfixture",
        "author": "science.example",
        "text": "Mars rover context.",
        "created_at": datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        "parent_texts": [],
        "quoted_texts": [],
        "links": [],
        "images": [],
        "warnings": [],
    }
    fields.update(overrides)
    return PostContext.model_construct(**cast(Any, fields))


def _service(rag_service: Any | None = None, **settings: object) -> RetrievalService:
    rag = rag_service or RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=100, overlap=10),
    )
    return RetrievalService(
        rag_service=cast(Any, rag),
        search_providers=[],
        settings=RetrievalSettings(**cast(Any, settings)),
    )


@pytest.mark.asyncio
async def test_malformed_search_provider_container_degrades_to_startup_warning() -> None:
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
            chunking=ChunkingConfig(name="test", size=100, overlap=10),
        ),
        search_providers=cast(Any, ExplodingIterable()),
        settings=RetrievalSettings(include_linked_pages=False),
    )

    result = await service.retrieve(_post(), queries=["mars"])

    assert "search_providers_iter_failed:RuntimeError" in result.warnings


@pytest.mark.asyncio
async def test_malformed_post_context_and_query_iterables_degrade_to_warnings() -> None:
    service = _service(include_linked_pages=False, include_search=False)
    post = _post(
        parent_texts=ExplodingIterable(),
        quoted_texts=ExplodingIterable(),
        images=ExplodingIterable(),
    )

    result = await service.retrieve(post, queries=cast(Any, ExplodingIterable()))

    assert [document.id for document in result.documents] == ["POST-target"]
    assert result.evidence == []
    assert "post_parent_texts_iter_failed:RuntimeError" in result.warnings
    assert "post_quoted_texts_iter_failed:RuntimeError" in result.warnings
    assert "post_images_iter_failed:RuntimeError" in result.warnings
    assert "supplied_queries_iter_failed:RuntimeError" in result.warnings


@pytest.mark.asyncio
async def test_malformed_created_at_accessor_degrades_in_post_metadata() -> None:
    service = _service(include_linked_pages=False, include_search=False)

    result = await service.retrieve(_post(created_at=BadCreatedAt()), queries=["mars"])

    assert result.documents[0].metadata["created_at"] == "context_text_failed:RuntimeError"


@pytest.mark.asyncio
async def test_malformed_link_iterables_degrade_before_fetching() -> None:
    service = _service(include_thread_context=False, include_search=False)

    result = await service.retrieve(_post(links=ExplodingIterable()), queries=["mars"])

    assert result.documents == []
    assert result.evidence == []
    assert "linked_page_iter_failed:RuntimeError" in result.warnings
    assert "retrieval_no_documents" in result.warnings


@pytest.mark.asyncio
async def test_link_iterables_are_not_read_past_configured_limit() -> None:
    service = _service(include_thread_context=False, include_search=False, linked_page_limit=1)

    result = await service.retrieve(_post(links=ExplodingAfterFirst()), queries=["mars"])

    assert "linked_page_iter_failed:RuntimeError" not in result.warnings
    assert any(
        warning.startswith("blocked_link:http://127.0.0.1/one")
        for warning in result.warnings
    )


@pytest.mark.asyncio
async def test_rag_diagnostics_failures_degrade_after_successful_evidence() -> None:
    service = _service(
        rag_service=BadDiagnosticsRagService(),
        include_linked_pages=False,
        include_search=False,
    )

    result = await service.retrieve(_post(), queries=["mars"])

    assert [item.id for item in result.evidence] == ["E1"]
    assert "retrieval_diagnostics_failed:RuntimeError" in result.warnings
