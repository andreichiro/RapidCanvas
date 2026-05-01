from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.ml.embeddings import DeterministicHashEmbeddingProvider
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, RagService
from app.schemas.domain import PostContext


def post_context_with_warning(warning: str) -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        warnings=[warning],
    )


@pytest.mark.asyncio
async def test_retrieval_promotes_upstream_block_warnings_to_private_blocks() -> None:
    upstream_block = "blocked_link:http://127.0.0.1/admin:blocked_non_public_ip:127.0.0.1"
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        settings=RetrievalSettings(include_linked_pages=False),
    )

    result = await service.retrieve(post_context_with_warning(upstream_block), queries=["mars"])

    assert upstream_block in result.warnings
    assert upstream_block in result.private_url_blocks
    assert "private_url_blocked" in result.guardrail_flags
    assert upstream_block in result.diagnostics.private_url_blocks


@pytest.mark.asyncio
async def test_retrieval_decodes_bytes_upstream_block_warnings_before_promotion() -> None:
    upstream_block = "blocked_link:http://127.0.0.1/admin:blocked_non_public_ip:127.0.0.1"
    post = PostContext.model_construct(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        parent_texts=[],
        quoted_texts=[],
        images=[],
        links=[],
        warnings=[upstream_block.encode("utf-8")],
    )
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        settings=RetrievalSettings(include_linked_pages=False),
    )

    result = await service.retrieve(post, queries=["mars"])

    assert upstream_block in result.warnings
    assert upstream_block in result.private_url_blocks


@pytest.mark.asyncio
async def test_retrieval_treats_string_upstream_warnings_as_one_warning() -> None:
    upstream_block = "blocked_link:http://127.0.0.1/admin:blocked_non_public_ip:127.0.0.1"
    post = PostContext.model_construct(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        parent_texts=[],
        quoted_texts=[],
        images=[],
        links=[],
        warnings=upstream_block,
    )
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        settings=RetrievalSettings(include_linked_pages=False),
    )

    result = await service.retrieve(post, queries=["mars"])

    assert upstream_block in result.warnings
    assert upstream_block in result.private_url_blocks
