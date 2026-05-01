from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from pytest import raises

from app.clients.bsky import (
    BlueskyClient,
    BlueskyClientError,
    InvalidBlueskyPostUrlError,
    parse_post_url,
)


@dataclass
class ResolveResponse:
    did: str


class FakeAtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:example")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "author": {"handle": "example.com"},
                    "record": {
                        "text": "Hello Bluesky with a link",
                        "created_at": "2026-04-29T12:00:00Z",
                        "facets": [{"features": [{"uri": "https://example.com/context"}]}],
                    },
                    "embed": {
                        "images": [
                            {
                                "fullsize": "https://cdn.example.com/image.jpg",
                                "alt": "Example image",
                            }
                        ]
                    },
                },
                "parent": {
                    "post": {
                        "record": {
                            "text": "Parent context",
                            "created_at": "2026-04-29T11:59:00Z",
                        }
                    }
                },
            }
        }


class FakeDidAtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        raise AssertionError(f"DID actor should not resolve handle: {handle}")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "author": {"did": "did:plc:example"},
                    "record": {
                        "text": "DID actor post",
                        "created_at": "2026-04-29T12:00:00Z",
                    },
                }
            }
        }


class FakeVideoAtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:example")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "author": {"handle": "example.com"},
                    "record": {
                        "text": "Watch this clip",
                        "created_at": "2026-04-29T12:00:00Z",
                    },
                    "embed": {
                        "$type": "app.bsky.embed.video#view",
                        "playlist": "https://video.cdn.example.com/playlist.m3u8",
                        "thumbnail": "https://video.cdn.example.com/thumb.jpg",
                    },
                }
            }
        }


class FakeAdvancedAtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:example")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        assert uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
        assert depth == 3
        assert parent_height == 2
        return {
            "thread": {
                "post": {
                    "uri": "at://did:plc:example/app.bsky.feed.post/3abcxyz",
                    "author": {"handle": "example.com"},
                    "record": {
                        "text": "Target with duplicate links and quote",
                        "created_at": "2026-04-29T12:00:00Z",
                        "facets": [
                            {"features": [{"uri": "https://example.com/context"}]},
                            {"features": [{"uri": "https://example.com/context"}]},
                        ],
                    },
                    "embed": {
                        "record": {
                            "value": {
                                "text": "Quoted post text",
                            }
                        },
                        "media": {
                            "images": [
                                {
                                    "thumb": "https://cdn.example.com/image-thumb.jpg",
                                    "alt": "Image from media embed",
                                }
                            ],
                            "external": {
                                "uri": "https://example.com/from-embed",
                            },
                        },
                    },
                },
                "parent": {
                    "post": {
                        "record": {
                            "text": "Immediate parent",
                            "created_at": "2026-04-29T11:59:00Z",
                        }
                    },
                    "parent": {
                        "$type": "app.bsky.feed.defs#notFoundPost",
                        "not_found": True,
                    },
                },
            }
        }


class FakeUnavailableAtprotoClient:
    def resolve_handle(self, handle: str) -> ResolveResponse:
        assert handle == "example.com"
        return ResolveResponse(did="did:plc:example")

    def get_post_thread(self, uri: str, depth: int, parent_height: int) -> dict[str, object]:
        return {
            "thread": {
                "$type": "app.bsky.feed.defs#notFoundPost",
                "not_found": True,
                "uri": uri,
            }
        }


class SearchParams(Protocol):
    q: str
    limit: int
    sort: str


class FakeSearchFeed:
    def search_posts(self, params: SearchParams) -> dict[str, object]:
        assert params.q == "rapidcanvas"
        assert params.limit == 2
        assert params.sort == "top"
        return {
            "posts": [
                {
                    "uri": "at://did:plc:result/app.bsky.feed.post/3search",
                    "author": {"handle": "result.example"},
                    "record": {
                        "text": "Search result post",
                        "created_at": "2026-04-29T10:00:00Z",
                        "facets": [
                            {"features": [{"uri": "https://example.com/search-context"}]}
                        ],
                    },
                    "embed": {
                        "images": [
                            {
                                "fullsize": "https://cdn.example.com/search.jpg",
                                "alt": "Search image",
                            }
                        ]
                    },
                }
            ]
        }


@dataclass
class UpstreamErrorResponse:
    status_code: int


class ExplodingSearchError(Exception):
    response = UpstreamErrorResponse(status_code=403)

    def __str__(self) -> str:
        return "<html>SECRET OR UNTRUSTED UPSTREAM BODY</html>"


class FailingSearchFeed:
    def search_posts(self, params: SearchParams) -> dict[str, object]:
        raise ExplodingSearchError()


@dataclass
class FakeBskyNamespace:
    feed: FakeSearchFeed | FailingSearchFeed


@dataclass
class FakeAppNamespace:
    bsky: FakeBskyNamespace


@dataclass
class FakeSearchAtprotoClient:
    app: FakeAppNamespace


def test_parse_post_url_extracts_actor_and_rkey() -> None:
    actor, rkey = parse_post_url("https://bsky.app/profile/example.com/post/3abcxyz")

    assert actor == "example.com"
    assert rkey == "3abcxyz"


def test_parse_post_url_rejects_non_bluesky_url() -> None:
    with raises(InvalidBlueskyPostUrlError):
        parse_post_url("https://example.com/profile/example.com/post/3abcxyz")


def test_fetch_context_normalizes_thread_response() -> None:
    client = BlueskyClient(client=FakeAtprotoClient())

    context = client.fetch_context("https://bsky.app/profile/example.com/post/3abcxyz")

    assert context.at_uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
    assert context.author == "example.com"
    assert context.text == "Hello Bluesky with a link"
    assert context.parent_texts == ["Parent context"]
    assert context.links == ["https://example.com/context"]
    assert context.images[0].alt_text == "Example image"


def test_fetch_context_supports_did_actor_without_handle_resolution() -> None:
    client = BlueskyClient(client=FakeDidAtprotoClient())

    context = client.fetch_context("https://bsky.app/profile/did:plc:example/post/3abcxyz")

    assert context.at_uri == "at://did:plc:example/app.bsky.feed.post/3abcxyz"
    assert context.author == "did:plc:example"
    assert context.text == "DID actor post"


def test_fetch_context_keeps_video_posts_working_with_unparsed_video_warning() -> None:
    client = BlueskyClient(client=FakeVideoAtprotoClient())

    context = client.fetch_context("https://bsky.app/profile/example.com/post/3abcxyz")

    assert context.text == "Watch this clip"
    assert context.metadata["has_unparsed_video"] is True
    assert context.metadata["unsupported_media"] == ["video"]
    assert any("video_embed_unparsed" in warning for warning in context.warnings)


def test_fetch_context_normalizes_quote_media_embed_links_images_and_warnings() -> None:
    client = BlueskyClient(client=FakeAdvancedAtprotoClient())

    context = client.fetch_context("https://bsky.app/profile/example.com/post/3abcxyz")

    assert context.quoted_texts == ["Quoted post text"]
    assert context.parent_texts == ["Immediate parent"]
    assert context.links == [
        "https://example.com/context",
        "https://example.com/from-embed",
    ]
    assert context.images[0].url == "https://cdn.example.com/image-thumb.jpg"
    assert context.images[0].alt_text == "Image from media embed"
    assert context.warnings == ["Parent Bluesky post is unavailable or deleted."]


def test_fetch_context_raises_for_unavailable_target_post() -> None:
    client = BlueskyClient(client=FakeUnavailableAtprotoClient())

    with raises(BlueskyClientError, match="Target Bluesky post is unavailable or deleted"):
        client.fetch_context("https://bsky.app/profile/example.com/post/3abcxyz")


def test_search_posts_returns_bluesky_context_documents() -> None:
    fake_client = FakeSearchAtprotoClient(
        app=FakeAppNamespace(bsky=FakeBskyNamespace(feed=FakeSearchFeed()))
    )
    client = BlueskyClient(client=fake_client)

    documents = client.search_posts("rapidcanvas", limit=2)

    assert len(documents) == 1
    assert documents[0].id == "BS1"
    assert documents[0].source_type == "bluesky"
    assert documents[0].url == "https://bsky.app/profile/result.example/post/3search"
    assert documents[0].text == "Search result post"
    assert documents[0].metadata["links"] == ["https://example.com/search-context"]
    assert documents[0].metadata["images"][0]["alt_text"] == "Search image"


def test_search_posts_wraps_upstream_failure_without_raw_body() -> None:
    fake_client = FakeSearchAtprotoClient(
        app=FakeAppNamespace(bsky=FakeBskyNamespace(feed=FailingSearchFeed()))
    )
    client = BlueskyClient(client=fake_client)

    with raises(BlueskyClientError) as error:
        client.search_posts("rapidcanvas", limit=2)

    message = str(error.value)
    assert message == "Unable to search Bluesky posts: ExplodingSearchError status=403"
    assert "SECRET" not in message
