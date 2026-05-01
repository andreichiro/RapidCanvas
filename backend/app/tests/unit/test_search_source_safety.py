from __future__ import annotations

from collections.abc import Sequence

import pytest

import app.clients.search as search
from app.schemas.domain import ContextDocument


class FakeNormalizedBlueskySearchClient:
    def __init__(self, url: str) -> None:
        self.url = url

    def search_posts(self, query: str, limit: int) -> list[ContextDocument]:
        assert query == "mars rover"
        assert limit == 1
        return [
            ContextDocument(
                id="BS1",
                source_type="bluesky",
                title="Bluesky post by space.example",
                url=self.url,
                text="Mars rover context with preserved normalized metadata.",
                metadata={"author": "space.example"},
            )
        ]


class MalformedNormalizedBlueskySearchClient:
    def search_posts(self, query: str, limit: int) -> list[ContextDocument]:
        assert query == "mars rover"
        assert limit == 1
        return [
            ContextDocument.model_construct(
                id="BS2",
                source_type=["bluesky"],
                title="Malformed normalized source",
                url=["https://example.com/malformed"],
                text="Mars rover context.",
                metadata=[],
            )
        ]


def resolver(hostname: str) -> Sequence[str]:
    if hostname == "127.0.0.1.nip.io":
        return ("127.0.0.1",)
    return ("93.184.216.34",)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "expected_warning"),
    [
        (
            "http://127.0.0.1/admin",
            "blocked_url:http://127.0.0.1/admin:blocked_non_public_ip:127.0.0.1",
        ),
        (
            "https://127.0.0.1.nip.io/admin",
            "blocked_url:https://127.0.0.1.nip.io/admin:blocked_non_public_ip:127.0.0.1",
        ),
    ],
)
async def test_bluesky_search_provider_blocks_unsafe_normalized_document_urls(
    url: str,
    expected_warning: str,
) -> None:
    provider = search.BlueskySearchProvider(
        client=FakeNormalizedBlueskySearchClient(url),
        resolver=resolver,
    )

    documents = await provider.search("mars rover", limit=1)

    assert documents == []
    assert expected_warning in provider.last_warnings
    assert "blocked_non_public_ip:127.0.0.1" in provider.last_warnings


@pytest.mark.asyncio
async def test_bluesky_search_provider_blocks_malformed_normalized_document_url() -> None:
    provider = search.BlueskySearchProvider(
        client=MalformedNormalizedBlueskySearchClient(),
        resolver=resolver,
    )

    documents = await provider.search("mars rover", limit=1)

    assert documents == []
    assert "blocked_url:<malformed_url>:blocked_malformed_url" in provider.last_warnings
