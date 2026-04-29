from __future__ import annotations

from dataclasses import dataclass

from pytest import raises

from app.clients.bsky import BlueskyClient, InvalidBlueskyPostUrlError, parse_post_url


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
