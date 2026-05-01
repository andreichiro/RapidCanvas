from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime

import httpx
import pytest

from app.clients.fetcher import LinkedPageFetcher
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, RagService
from app.schemas.domain import PostContext


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [normalize_vector([1.0 if "mars" in text.lower() else 0.0]) for text in texts]


def public_resolver(hostname: str) -> Sequence[str]:
    assert hostname == "example.com"
    return ("93.184.216.34",)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


def post_context() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/science.example/post/3kfixture",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kfixture",
        author="science.example",
        text="Mars rover thread asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 29, 12, 0, tzinfo=UTC),
        links=["https://example.com/one", "https://example.com/two"],
    )


class ExplodingLinks:
    def __iter__(self) -> Iterator[str]:
        yield "https://example.com/one"
        raise RuntimeError("iterated beyond link cap")


@pytest.mark.asyncio
async def test_retrieval_caps_linked_page_fetches() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Linked Mars context.</body></html>",
            request=request,
        )

    fetcher = LinkedPageFetcher(resolver=public_resolver, client_factory=client_factory(handler))
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        linked_page_fetcher=fetcher,
        settings=RetrievalSettings(include_thread_context=False, linked_page_limit=1),
    )

    result = await service.retrieve(post_context(), queries=["mars rover water"])

    assert seen_urls == ["https://example.com/one"]
    assert any(warning == "linked_page_limit_exceeded:1" for warning in result.warnings)
    assert [document.url for document in result.documents] == ["https://example.com/one"]


@pytest.mark.asyncio
async def test_retrieval_does_not_iterate_links_past_cap() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Linked Mars context.</body></html>",
            request=request,
        )

    fields = post_context().model_dump()
    fields["links"] = ExplodingLinks()
    fetcher = LinkedPageFetcher(resolver=public_resolver, client_factory=client_factory(handler))
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        linked_page_fetcher=fetcher,
        settings=RetrievalSettings(include_thread_context=False, linked_page_limit=1),
    )

    result = await service.retrieve(PostContext.model_construct(**fields), queries=["mars"])

    assert seen_urls == ["https://example.com/one"]
    assert [document.url for document in result.documents] == ["https://example.com/one"]
