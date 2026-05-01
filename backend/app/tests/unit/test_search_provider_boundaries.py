from __future__ import annotations

import asyncio
from collections.abc import Iterator, Mapping
from threading import Event, Thread
from typing import Any, cast

import pytest

from app.clients.extraction import sanitize_search_hit_document
from app.clients.search import BlueskySearchProvider, WebSearchProvider, collect_search_context
from app.schemas.domain import ContextDocument


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("bad string")


class BadMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        del key
        raise RuntimeError("bad mapping")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("bad mapping")

    def __len__(self) -> int:
        return 1


class BadProviderIterable:
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("provider iterator failed")


@pytest.mark.asyncio
async def test_built_in_providers_degrade_bad_result_shapes() -> None:
    class ExplodingPost:
        @property
        def record(self) -> object:
            raise RuntimeError("post shape failed")

    class ExplodingClient:
        def search_posts(self, query: str, limit: int) -> list[object]:
            del query, limit
            return [ExplodingPost()]

    class ExplodingHit(dict[str, str]):
        def get(self, key: object, default: object = None) -> object:  # type: ignore[override]
            del key, default
            raise RuntimeError("hit shape failed")

    class ExplodingDDGS:
        def text(self, query: str, max_results: int) -> list[dict[str, str]]:
            del query, max_results
            return [ExplodingHit()]

    bluesky = await BlueskySearchProvider(
        client=ExplodingClient(),
    ).search_with_warnings("mars", limit=1)
    web = await WebSearchProvider(
        ddgs_factory=lambda: ExplodingDDGS(),
    ).search_with_warnings("mars", limit=1)

    assert bluesky.documents == []
    assert bluesky.warnings == ["bluesky_search_invalid_item:1:RuntimeError"]
    assert web.documents == []
    assert web.warnings == ["web_search_invalid_hit:1:RuntimeError"]


@pytest.mark.asyncio
async def test_built_in_providers_degrade_bad_query_text() -> None:
    class CapturingClient:
        query = ""

        def search_posts(self, query: str, limit: int) -> list[object]:
            del limit
            self.query = query
            return []

    class CapturingDDGS:
        query = ""

        def text(self, query: str, max_results: int) -> list[dict[str, Any]]:
            del max_results
            self.query = query
            return []

    client = CapturingClient()
    ddgs = CapturingDDGS()

    bluesky = await BlueskySearchProvider(client=client).search_with_warnings(
        cast(str, BadString()), limit=1
    )
    web = await WebSearchProvider(ddgs_factory=lambda: ddgs).search_with_warnings(
        cast(str, BadString()), limit=1
    )

    assert bluesky.documents == []
    assert web.documents == []
    assert client.query == "search_query_text_failed:RuntimeError"
    assert ddgs.query == "search_query_text_failed:RuntimeError"


@pytest.mark.asyncio
async def test_bluesky_provider_degrades_missing_document_url() -> None:
    class MissingUrlClient:
        def search_posts(self, query: str, limit: int) -> list[ContextDocument]:
            del query, limit
            return [
                ContextDocument.model_construct(
                    id="D1",
                    source_type="web",
                    title="Doc",
                    text="Mars context.",
                    metadata={},
                )
            ]

    bundle = await BlueskySearchProvider(client=MissingUrlClient()).search_with_warnings(
        "mars", limit=1
    )

    assert bundle.documents == []
    assert any(warning.startswith("blocked_url:") for warning in bundle.warnings)
    assert any("blocked_unsupported_scheme" in warning for warning in bundle.warnings)


def test_search_hit_sanitizer_degrades_bad_document_metadata() -> None:
    document = ContextDocument.model_construct(
        id="D1",
        source_type="web",
        title="Doc",
        url="https://example.com",
        text="Mars context.",
        metadata=BadMapping(),
    )

    sanitized, _scan = sanitize_search_hit_document(document, {}, query="mars", index=1)

    assert sanitized.metadata["metadata_iter_failed"] == "metadata_iter_failed:RuntimeError"


@pytest.mark.asyncio
async def test_collect_search_context_degrades_bad_provider_container() -> None:
    bundle = await collect_search_context("mars", cast(Any, BadProviderIterable()), 1)

    assert bundle.documents == []
    assert bundle.warnings == ["search_providers_iter_failed:RuntimeError"]


def test_builtin_provider_last_warnings_are_thread_local() -> None:
    class QueryDDGS:
        def text(self, query: str, max_results: int) -> list[dict[str, str]]:
            del max_results
            return [{"title": query, "href": f"http://127.0.0.1/{query}", "body": query}]

    provider = WebSearchProvider(ddgs_factory=lambda: QueryDDGS())
    alpha_retrieved = Event()
    beta_done = Event()
    results: dict[str, list[str]] = {}

    def run_alpha() -> None:
        asyncio.run(provider.search("alpha", limit=1))
        alpha_retrieved.set()
        assert beta_done.wait(timeout=5)
        results["alpha"] = list(provider.last_warnings)

    def run_beta() -> None:
        assert alpha_retrieved.wait(timeout=5)
        asyncio.run(provider.search("beta", limit=1))
        results["beta"] = list(provider.last_warnings)
        beta_done.set()

    alpha = Thread(target=run_alpha)
    beta = Thread(target=run_beta)
    alpha.start()
    beta.start()
    alpha.join(timeout=5)
    beta.join(timeout=5)

    assert any("/alpha" in warning for warning in results["alpha"])
    assert all("/beta" not in warning for warning in results["alpha"])
    assert any("/beta" in warning for warning in results["beta"])


def test_builtin_provider_last_warnings_remain_list_like() -> None:
    class QueryDDGS:
        def text(self, query: str, max_results: int) -> list[dict[str, str]]:
            del query, max_results
            return [{"title": "blocked", "href": "http://127.0.0.1/admin", "body": "blocked"}]

    provider = WebSearchProvider(ddgs_factory=lambda: QueryDDGS())

    assert provider.last_warnings == []
    assert len(provider.last_warnings) == 0
    assert not provider.last_warnings

    asyncio.run(provider.search("alpha", limit=1))

    assert provider.last_warnings
    assert len(provider.last_warnings) >= 2
    assert provider.last_warnings[0].startswith("blocked_url:")
    assert list(provider.last_warnings) == provider.last_warnings.get()
    assert provider.last_warnings != "blocked_url"
