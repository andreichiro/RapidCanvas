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


class DnsPrivateSourceProvider:
    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        assert query == "mars rover water"
        assert limit == 4
        return [
            ContextDocument(
                id="DNS-PRIVATE",
                source_type="web",
                title="DNS private source",
                url="https://127.0.0.1.nip.io/admin",
                text="This provider document should be blocked before C2 handoff.",
                metadata={},
            ),
            ContextDocument(
                id="DNS-PRIVATE-IMAGE",
                source_type="image",
                title="DNS private image source",
                url="https://127.0.0.1.nip.io/image.png",
                text="Image source metadata should be blocked too.",
                metadata={},
            ),
            ContextDocument(
                id="DNS-PRIVATE-BLUESKY",
                source_type="bluesky",
                title="DNS private normalized source",
                url="https://127.0.0.1.nip.io/post",
                text="Normalized provider source metadata should also be blocked.",
                metadata={},
            ),
            ContextDocument(
                id="DNS-PRIVATE-THREAD",
                source_type="thread",
                title="DNS private thread source",
                url="https://127.0.0.1.nip.io/thread",
                text="Thread source metadata should be resolver-blocked.",
                metadata={},
            ),
        ]


def resolver(hostname: str) -> Sequence[str]:
    if hostname == "127.0.0.1.nip.io":
        return ("127.0.0.1",)
    return ("93.184.216.34",)


def post_context() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_retrieval_blocks_dns_private_provider_source_urls() -> None:
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[DnsPrivateSourceProvider()],
        linked_page_fetcher=LinkedPageFetcher(resolver=resolver),
        settings=RetrievalSettings(
            include_thread_context=False,
            include_linked_pages=False,
            search_limit_per_provider=4,
        ),
    )

    result = await service.retrieve(post_context(), queries=["mars rover water"])

    assert result.documents == []
    assert "private_url_blocked" in result.guardrail_flags
    assert result.private_url_blocks == [
        "blocked_document_url:DNS-PRIVATE:"
        "https://127.0.0.1.nip.io/admin:"
        "blocked_non_public_ip:127.0.0.1",
        "blocked_document_url:DNS-PRIVATE-IMAGE:"
        "https://127.0.0.1.nip.io/image.png:"
        "blocked_non_public_ip:127.0.0.1",
        "blocked_document_url:DNS-PRIVATE-BLUESKY:"
        "https://127.0.0.1.nip.io/post:"
        "blocked_non_public_ip:127.0.0.1",
        "blocked_document_url:DNS-PRIVATE-THREAD:"
        "https://127.0.0.1.nip.io/thread:"
        "blocked_non_public_ip:127.0.0.1",
    ]
