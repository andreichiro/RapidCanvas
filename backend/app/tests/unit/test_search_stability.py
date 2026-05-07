from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx
import pytest

import app.clients.search as search
from app.clients.fetcher import LinkedPageFetcher
from app.clients.robots import RobotsPolicy


def public_resolver(hostname: str) -> Sequence[str]:
    assert hostname in {"example.com", "www.example.com"}
    return ("93.184.216.34",)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


class FakeDDGS:
    def __init__(self, hits: list[dict[str, str]]) -> None:
        self._hits = hits

    def text(self, query: str, max_results: int) -> list[dict[str, str]]:
        assert query == "mars rover"
        return self._hits[:max_results]


@pytest.mark.asyncio
async def test_web_search_provider_canonicalizes_result_domains() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://www.example.com/context"
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Mars rover context from a canonical domain.</body></html>",
            request=request,
        )

    fetcher = LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
    )
    provider = search.WebSearchProvider(
        fetcher=fetcher,
        ddgs_factory=lambda: FakeDDGS(
            [
                {
                    "title": "Mars rover canonical result",
                    "href": "https://www.Example.com/context",
                    "body": "Search snippet for Mars rover context.",
                }
            ]
        ),
    )

    documents = await provider.search("mars rover", limit=1)

    assert len(documents) == 1
    assert documents[0].metadata["domain"] == "example.com"


@pytest.mark.asyncio
async def test_web_search_provider_keeps_robots_disallowed_snippet_as_low_confidence() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(
                200,
                text="User-agent: *\nDisallow: /blocked\n",
                request=request,
            )
        raise AssertionError(f"robots-disallowed page should not be fetched: {request.url}")

    fetcher = LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
        robots_policy=RobotsPolicy(
            client_factory=client_factory(handler),
            resolver=public_resolver,
        ),
    )
    provider = search.WebSearchProvider(
        fetcher=fetcher,
        ddgs_factory=lambda: FakeDDGS(
            [
                {
                    "title": "Mars rover source",
                    "href": "https://example.com/blocked",
                    "body": "Snippet-only Mars rover context from a robots-disallowed page.",
                }
            ]
        ),
    )

    documents = await provider.search("mars rover", limit=1)

    assert requested_paths == ["/robots.txt"]
    assert len(documents) == 1
    assert documents[0].metadata["snippet_only"] is True
    assert documents[0].metadata["fetch_success"] is False
    assert documents[0].metadata["robots_disallowed"] is True
    assert documents[0].metadata["fetch_status"] == "robots_disallowed"
    assert "robots_disallowed" in documents[0].metadata["fetch_warnings"]
    assert "robots_disallowed" in provider.last_warnings
    assert all(not warning.startswith("blocked_url:") for warning in provider.last_warnings)
