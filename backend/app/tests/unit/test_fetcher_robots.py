from __future__ import annotations

from collections.abc import Callable, Sequence

import httpx
import pytest

from app.clients.fetcher import LinkedPageFetcher
from app.clients.robots import RobotsPolicy


def public_resolver(hostname: str) -> Sequence[str]:
    assert hostname == "example.com"
    return ("93.184.216.34",)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


@pytest.mark.asyncio
async def test_linked_page_fetcher_respects_robots_disallow_without_fetching_page() -> None:
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

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)
    fetcher = LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
        robots_policy=policy,
    )

    result = await fetcher.fetch("https://example.com/blocked")

    assert requested_paths == ["/robots.txt"]
    assert result.document is None
    assert result.blocked is False
    assert result.warnings == ("robots_disallowed",)


@pytest.mark.asyncio
async def test_linked_page_fetcher_fetches_page_when_robots_allows() -> None:
    requested_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_paths.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n", request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Allowed robots context.</body></html>",
            request=request,
        )

    policy = RobotsPolicy(client_factory=client_factory(handler), resolver=public_resolver)
    fetcher = LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
        robots_policy=policy,
    )

    result = await fetcher.fetch("https://example.com/context")

    assert requested_paths == ["/robots.txt", "/context"]
    assert result.document is not None
    assert "Allowed robots context." in result.document.text
