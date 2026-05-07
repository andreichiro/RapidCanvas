from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
from pydantic import TypeAdapter

from app.clients.fetcher import LinkedPageFetcher
from app.clients.search import BlueskySearchProvider, WebSearchProvider
from app.ml.diagnostics import RetrievalResult
from app.ml.embeddings import normalize_vector
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_payload import retrieval_result_payload
from app.ml.retrieval_service import RetrievalService, RetrievalSettings, build_retrieval_service
from app.ml.vector_store import ChunkingConfig, InMemoryVectorStore, RagService
from app.schemas.domain import ContextDocument, Evidence, PostContext

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "gate5_retrieval"
_SCIENCE_AT_URI = "at://did:plc:science/app.bsky.feed.post/3kabc"


class KeywordEmbeddingProvider:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        lowered = text.lower()
        return normalize_vector(
            [
                1.0 if "mars" in lowered or "rover" in lowered else 0.0,
                1.0 if "water" in lowered or "hydrated" in lowered else 0.0,
                1.0 if "api key" in lowered or "ignore instructions" in lowered else 0.0,
            ]
        )


class FakeNormalizedSearchProvider:
    last_warnings = ["search_fixture_warning"]

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        assert query == "mars rover water"
        assert limit == 2
        return [
            ContextDocument(
                id="BSKY-normalized",
                source_type="bluesky",
                title="Bluesky post by science.example",
                url="https://bsky.app/profile/science.example/post/3kabc",
                text="Mars rover evidence from a normalized Bluesky search result.",
                metadata={"author": "science.example", "at_uri": _SCIENCE_AT_URI},
            )
        ]


class UnsafeUrlSearchProvider:
    last_warnings: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        assert query == "mars rover water"
        assert limit == 1
        return [
            ContextDocument(
                id="UNSAFE-DOC", source_type="web", title="Unsafe source",
                url="https://user:pass@example.com/private",
                text="This document should be blocked before retrieval.",
                metadata={},
            )
        ]


class CountingBlueskySearchClient:
    def __init__(self) -> None:
        self.calls = 0

    def search_posts(self, query: str, limit: int) -> list[ContextDocument]:
        del query, limit
        self.calls += 1
        return []


class CountingDDGS:
    def __init__(self) -> None:
        self.calls = 0

    def text(self, query: str, max_results: int) -> list[dict[str, str]]:
        del query, max_results
        self.calls += 1
        return []


def public_resolver(hostname: str) -> Sequence[str]:
    del hostname
    return ("93.184.216.34",)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


def load_post_context() -> PostContext:
    data = json.loads((FIXTURE_DIR / "post_context.json").read_text())
    return PostContext.model_validate(data)

def load_c2_fixture() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads((FIXTURE_DIR / "c2_retrieval_result.json").read_text()))


@pytest.mark.asyncio
async def test_gate5_retrieval_turns_post_context_into_c2_result() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://example.com/mars-water"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text=(
                "<html><title>Mars water context</title>"
                "<body><article>Hydrated minerals add water context for the Mars rover."
                "</article></body></html>"
            ),
            request=request,
        )

    fetcher = LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
    )
    rag_service = RagService(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        chunking=ChunkingConfig(name="test", size=220, overlap=20),
        retrieve_limit=12,
        evidence_limit=4,
    )
    service = RetrievalService(
        rag_service=rag_service,
        search_providers=[FakeNormalizedSearchProvider()],
        linked_page_fetcher=fetcher,
        settings=RetrievalSettings(search_limit_per_provider=2, evidence_limit=4),
    )
    result = await service.retrieve(load_post_context(), queries=["mars rover water"])
    assert result.queries == ["mars rover water"]
    assert result.evidence
    assert result.diagnostics.document_count == len(result.documents)
    assert result.diagnostics.evidence_count == len(result.evidence)
    assert result.source_ids == list(dict.fromkeys(item.source_id for item in result.evidence))
    assert result.scores[result.evidence[0].id] == result.evidence[0].score
    assert "prompt_injection_risk" in result.guardrail_flags
    assert "ignore_previous_instructions" in result.guardrail_flags
    assert "api_key_request" in result.guardrail_flags
    assert "private_url_blocked" in result.guardrail_flags
    assert any("127.0.0.1" in block for block in result.private_url_blocks)
    assert any(document.metadata["sanitized"] is True for document in result.documents)

    normalized = next(document for document in result.documents if document.id == "BSKY-normalized")
    assert normalized.title == "Bluesky post by science.example"
    assert normalized.url == "https://bsky.app/profile/science.example/post/3kabc"
    assert normalized.metadata["author"] == "science.example"
    assert normalized.metadata["at_uri"] == "at://did:plc:science/app.bsky.feed.post/3kabc"
    assert_c2_fixture_matches_result(load_c2_fixture(), result)


def test_c2_retrieval_fixture_is_dev_c_consumable() -> None:
    fixture = load_c2_fixture()
    documents = TypeAdapter(list[ContextDocument]).validate_python(fixture["documents"])
    evidence = TypeAdapter(list[Evidence]).validate_python(fixture["evidence"])
    document_ids = {document.id for document in documents}
    evidence_ids = {item.id for item in evidence}
    warning_document_ids = {
        warning.split(":", maxsplit=2)[1]
        for warning in fixture["warnings"]
        if warning.startswith("prompt_injection_risk:")
    }

    assert documents
    assert evidence
    assert fixture["diagnostics"]["document_count"] == len(documents)
    assert fixture["diagnostics"]["evidence_count"] == len(evidence)
    assert all(item.document_id in document_ids for item in evidence)
    assert all(source_id in document_ids for source_id in fixture["source_ids"])
    assert warning_document_ids <= document_ids
    assert fixture["diagnostics"]["source_ids"] == fixture["source_ids"]
    assert fixture["diagnostics"]["evidence_scores"] == fixture["scores"]
    assert fixture["diagnostics"]["warnings"] == fixture["warnings"]
    assert fixture["diagnostics"]["private_url_blocks"] == fixture["private_url_blocks"]
    assert set(fixture["scores"]) == evidence_ids
    assert "prompt_injection_risk" in fixture["guardrail_flags"]
    assert "private_url_blocked" in fixture["guardrail_flags"]
    assert any(
        block.startswith("blocked_link:http://127.0.0.1")
        for block in fixture["private_url_blocks"]
    )

def test_build_retrieval_service_respects_explicit_empty_search_providers() -> None:
    service = build_retrieval_service(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        search_providers=[],
    )
    assert service._search_providers == []


@pytest.mark.asyncio
async def test_gate5_retrieval_blocks_malformed_post_links() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"malformed URL should not be fetched: {request.url}")

    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        linked_page_fetcher=LinkedPageFetcher(
            resolver=public_resolver,
            client_factory=client_factory(handler),
        ),
    )
    post = load_post_context().model_copy(update={"links": ["http://[::1"]})
    result = await service.retrieve(post, queries=["mars rover water"])
    assert "private_url_blocked" in result.guardrail_flags
    assert any("blocked_malformed_url" in block for block in result.private_url_blocks)


@pytest.mark.asyncio
async def test_retrieval_respects_per_call_search_provider_settings() -> None:
    bsky_client = CountingBlueskySearchClient()
    ddgs = CountingDDGS()

    def ddgs_factory() -> CountingDDGS:
        return ddgs

    service = build_retrieval_service(
        embedding_provider=KeywordEmbeddingProvider(),
        vector_store=InMemoryVectorStore(),
        reranker=SimilarityReranker(),
        search_providers=[
            BlueskySearchProvider(client=bsky_client),
            WebSearchProvider(ddgs_factory=ddgs_factory),
        ],
    )
    await service.retrieve(
        load_post_context(),
        queries=["mars rover water"],
        settings=RetrievalSettings(
            include_linked_pages=False,
            include_bluesky_search=False,
            include_web_search=True,
        ),
    )
    await service.retrieve(
        load_post_context(),
        queries=["mars rover water"],
        settings=RetrievalSettings(
            include_linked_pages=False,
            include_bluesky_search=False,
            include_web_search=False,
        ),
    )
    assert bsky_client.calls == 0
    assert ddgs.calls == 1


@pytest.mark.asyncio
async def test_retrieval_blocks_unsafe_provider_document_urls() -> None:
    service = RetrievalService(
        rag_service=RagService(
            embedding_provider=KeywordEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[UnsafeUrlSearchProvider()],
        settings=RetrievalSettings(
            include_thread_context=False,
            include_linked_pages=False,
            search_limit_per_provider=1,
        ),
    )
    result = await service.retrieve(load_post_context(), queries=["mars rover water"])
    assert result.documents == []
    assert "private_url_blocked" in result.guardrail_flags
    assert result.private_url_blocks == [
        "blocked_document_url:UNSAFE-DOC:https://example.com/private:blocked_url_userinfo"
    ]
    assert "user:pass" not in "\n".join(result.warnings)

def assert_c2_fixture_matches_result(
    fixture: dict[str, Any],
    result: RetrievalResult,
) -> None:
    payload = retrieval_result_payload(result)
    assert fixture["queries"] == payload["queries"]
    assert fixture["private_url_blocks"] == payload["private_url_blocks"]
    assert fixture["guardrail_flags"] == payload["guardrail_flags"]
    assert fixture["diagnostics"]["document_count"] == payload["diagnostics"]["document_count"]
    assert fixture["diagnostics"]["evidence_count"] == payload["diagnostics"]["evidence_count"]
    assert {document["id"] for document in fixture["documents"]} == {
        document["id"] for document in payload["documents"]
    }
    assert {item["document_id"] for item in fixture["evidence"]} == {
        item["document_id"] for item in payload["evidence"]
    }
    for document in payload["documents"]:
        metadata = document["metadata"]
        assert "source_quality_score" in metadata
        assert "source_quality_reasons" in metadata
        assert "citation_eligible" in metadata
