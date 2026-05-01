from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import cast

import httpx
import pytest

from app.clients.fetcher import LinkedPageFetcher, validate_public_http_url


class BadString:
    def __str__(self) -> str:
        raise RuntimeError("bad string")


class FakeNetworkStream:
    def get_extra_info(self, name: str) -> object:
        return (BadString(), 443) if name == "peername" else None


def public_resolver(hostname: str) -> Sequence[str]:
    assert hostname == "example.com"
    return ("93.184.216.34",)


def bad_address_resolver(hostname: str) -> Sequence[str]:
    assert hostname == "example.com"
    return (cast(str, BadString()),)


def client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.AsyncClient]:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    return factory


@pytest.mark.asyncio
async def test_linked_page_fetcher_degrades_bad_source_id() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Useful context.</body></html>",
            request=request,
        )

    result = await LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
    ).fetch("https://example.com/context", source_id=cast(str, BadString()))

    assert result.document is not None
    assert result.document.id == "source_id_text_failed:RuntimeError"


def test_validate_public_http_url_blocks_malformed_resolver_addresses() -> None:
    result = validate_public_http_url("https://example.com", resolver=bad_address_resolver)

    assert result.allowed is False
    assert result.warnings[0].startswith("dns_resolution_invalid:example.com:")


@pytest.mark.asyncio
async def test_linked_page_fetcher_degrades_bad_peer_host_text() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Useful context.</body></html>",
            request=request,
            extensions={"network_stream": FakeNetworkStream()},
        )

    result = await LinkedPageFetcher(
        resolver=public_resolver,
        client_factory=client_factory(handler),
    ).fetch("https://example.com/context")

    assert result.document is not None
    assert result.blocked is False
