from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from app.clients.fetcher import LinkedPageFetcher
from app.ml.embeddings import DeterministicHashEmbeddingProvider
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, PostContext


class SanitizedIdCollisionProvider:
    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        del query, limit
        return [
            ContextDocument(
                id="<b>DUP</b>",
                source_type="web",
                title="First",
                url="https://example.com/first",
                text="First Mars context.",
                metadata={},
            ),
            ContextDocument(
                id="DUP",
                source_type="web",
                title="Second",
                url="https://example.com/second",
                text="Second Mars context.",
                metadata={},
            ),
        ]


def resolver(hostname: str) -> Sequence[str]:
    del hostname
    return ("93.184.216.34",)


def post_context() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_c2_result_keeps_sanitized_document_ids_unique() -> None:
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
            evidence_limit=0,
        ),
        search_providers=[SanitizedIdCollisionProvider()],
        linked_page_fetcher=LinkedPageFetcher(resolver=resolver),
        settings=RetrievalSettings(
            include_thread_context=False,
            include_linked_pages=False,
            search_limit_per_provider=2,
            evidence_limit=0,
        ),
    )

    result = await service.retrieve(post_context(), queries=["mars"])

    assert [document.id for document in result.documents] == ["DUP", "DUP-2"]
