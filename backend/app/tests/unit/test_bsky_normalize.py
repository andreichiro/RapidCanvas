from __future__ import annotations

from datetime import UTC, datetime

from pytest import raises

from app.clients.bsky_normalize import (
    DETERMINISTIC_TIMESTAMP_FALLBACK,
    normalize_thread,
    record_created_at,
    search_document,
)
from app.clients.bsky_url import post_ref_for_did


def test_malformed_created_at_uses_indexed_at_with_visible_warning() -> None:
    post = {
        "indexed_at": "2026-05-06T12:00:00Z",
        "author": {"handle": "example.com"},
        "record": {"text": "Malformed timestamp", "created_at": "not-a-date"},
    }

    timestamp = record_created_at(post)

    assert timestamp.value == datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    assert timestamp.source == "indexed_at"
    assert timestamp.warnings == ["created_at_parse_failed"]


def test_missing_created_at_uses_deterministic_fallback_with_warning() -> None:
    timestamp = record_created_at(
        {
            "author": {"handle": "example.com"},
            "record": {"text": "Missing timestamp"},
        }
    )

    assert timestamp.value == DETERMINISTIC_TIMESTAMP_FALLBACK
    assert timestamp.source == "deterministic_fallback"
    assert timestamp.warnings == ["created_at_missing"]


def test_missing_created_at_uses_indexed_at_with_visible_warning() -> None:
    timestamp = record_created_at(
        {
            "indexed_at": "2026-05-06T12:00:00Z",
            "author": {"handle": "example.com"},
            "record": {"text": "Missing timestamp"},
        }
    )

    assert timestamp.value == datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    assert timestamp.source == "indexed_at"
    assert timestamp.warnings == ["created_at_missing"]


def test_malformed_created_at_and_indexed_at_use_deterministic_fallback() -> None:
    timestamp = record_created_at(
        {
            "indexed_at": "also-bad",
            "author": {"handle": "example.com"},
            "record": {"text": "Bad timestamps", "created_at": "not-a-date"},
        }
    )

    assert timestamp.value == DETERMINISTIC_TIMESTAMP_FALLBACK
    assert timestamp.source == "deterministic_fallback"
    assert timestamp.warnings == ["created_at_parse_failed"]


def test_normalize_thread_surfaces_timestamp_video_and_parent_warnings() -> None:
    context = normalize_thread(
        "https://bsky.app/profile/example.com/post/3abcxyz",
        post_ref_for_did("example.com", "3abcxyz", "did:plc:example"),
        {
            "thread": {
                "post": {
                    "uri": "at://did:plc:example/app.bsky.feed.post/3abcxyz",
                    "indexed_at": "2026-05-06T12:00:00Z",
                    "author": {"handle": "example.com"},
                    "record": {"text": "Video post", "created_at": "bad-date"},
                    "embed": {"$type": "app.bsky.embed.video#view"},
                },
                "parent": {"$type": "app.bsky.feed.defs#notFoundPost", "not_found": True},
            }
        },
    )

    assert context.created_at == datetime(2026, 5, 6, 12, 0, tzinfo=UTC)
    assert context.metadata["created_at_source"] == "indexed_at"
    assert "created_at_parse_failed" in context.warnings
    assert "Parent Bluesky post is unavailable or deleted." in context.warnings
    assert any(warning.startswith("video_embed_unparsed:") for warning in context.warnings)


def test_search_document_metadata_surfaces_timestamp_warnings() -> None:
    document = search_document(
        {
            "uri": "at://did:plc:result/app.bsky.feed.post/3search",
            "indexed_at": "2026-05-06T12:00:00Z",
            "author": {"handle": "result.example"},
            "record": {"text": "Search result", "created_at": "bad-date"},
        },
        index=2,
    )

    assert document.id == "BS2"
    assert document.url == "https://bsky.app/profile/result.example/post/3search"
    assert document.metadata["created_at_source"] == "indexed_at"
    assert document.metadata["timestamp_warnings"] == ["created_at_parse_failed"]


def test_normalize_thread_surfaces_quote_timestamp_warnings() -> None:
    context = normalize_thread(
        "https://bsky.app/profile/example.com/post/3abcxyz",
        post_ref_for_did("example.com", "3abcxyz", "did:plc:example"),
        {
            "thread": {
                "post": {
                    "uri": "at://did:plc:example/app.bsky.feed.post/3abcxyz",
                    "author": {"handle": "example.com"},
                    "record": {
                        "text": "Target quoting a missing timestamp",
                        "created_at": "2026-05-06T12:00:00Z",
                    },
                    "embed": {
                        "record": {
                            "uri": "at://did:plc:quote/app.bsky.feed.post/3quote",
                            "author": {"handle": "quote.example"},
                            "value": {"text": "Quoted post with missing timestamp"},
                        }
                    },
                }
            }
        },
    )

    assert context.quoted_texts == ["Quoted post with missing timestamp"]
    assert context.quoted_posts[0].metadata["timestamp_warnings"] == ["created_at_missing"]
    assert "created_at_missing" in context.warnings


def test_normalize_thread_raises_for_blocked_or_deleted_target() -> None:
    with raises(ValueError, match="Target Bluesky post is blocked"):
        normalize_thread(
            "https://bsky.app/profile/example.com/post/3abcxyz",
            post_ref_for_did("example.com", "3abcxyz", "did:plc:example"),
            {"thread": {"$type": "app.bsky.feed.defs#blockedPost", "blocked": True}},
        )
