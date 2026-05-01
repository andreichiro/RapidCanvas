from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, PostContext


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0]) for text in texts]


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("bad string")


class Provider:
    def __init__(self, document: ContextDocument) -> None:
        self.document = document

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        del query, limit
        return [self.document]


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


def _service(provider: Provider | None = None, **settings: object) -> RetrievalService:
    return RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[] if provider is None else [provider],
        settings=RetrievalSettings(**cast(Any, settings)),
    )


@pytest.mark.asyncio
async def test_bad_string_link_objects_degrade_to_block_evidence() -> None:
    result = await _service(include_thread_context=False, include_search=False).retrieve(
        _post(links=[BadString()]),
        queries=["mars"],
    )

    assert result.documents == []
    assert result.private_url_blocks == ["blocked_link:<malformed_url>:blocked_malformed_url"]
    assert "private_url_blocked" in result.guardrail_flags


@pytest.mark.asyncio
async def test_bad_string_provider_document_ids_are_sanitized_before_dedupe() -> None:
    document = ContextDocument.model_construct(
        id=BadString(),
        source_type="web",
        title="Safe source",
        url="https://example.com/context",
        text="Mars rover context.",
        metadata={},
    )

    result = await _service(
        Provider(document),
        include_thread_context=False,
        include_linked_pages=False,
    ).retrieve(_post(), queries=["mars"])

    assert [item.id for item in result.documents] == ["identifier_text_failed:RuntimeError"]
    assert result.evidence


@pytest.mark.asyncio
async def test_bad_string_provider_source_types_degrade_before_url_filtering() -> None:
    document = ContextDocument.model_construct(
        id="DOC1",
        source_type=BadString(),
        title="Safe source",
        url="https://example.com/context",
        text="Mars rover context.",
        metadata={},
    )

    result = await _service(
        Provider(document),
        include_thread_context=False,
        include_linked_pages=False,
    ).retrieve(_post(), queries=["mars"])

    assert [item.id for item in result.documents] == ["DOC1"]
    assert result.documents[0].source_type == "web"
