from __future__ import annotations

from app.clients import bsky_embeds as embeds
from app.clients.bsky_normalize import parse_optional_datetime


def test_external_links_dedupe_facets_and_enrich_from_embed() -> None:
    post = {
        "record": {
            "facets": [
                {"features": [{"uri": "https://example.com/context"}]},
                {"features": [{"uri": "https://example.com/context"}]},
            ]
        },
        "embed": {
            "external": {
                "uri": "https://example.com/context",
                "title": "Context",
                "description": "Linked context",
                "thumb": "https://cdn.example.com/thumb.jpg",
            }
        },
    }

    links = embeds.external_links(post)

    assert len(links) == 1
    assert links[0].url == "https://example.com/context"
    assert links[0].title == "Context"
    assert links[0].description == "Linked context"
    assert links[0].thumb_url == "https://cdn.example.com/thumb.jpg"


def test_embed_images_extracts_media_images_once() -> None:
    post = {
        "embed": {
            "media": {
                "images": [
                    {
                        "fullsize": "https://cdn.example.com/image.jpg",
                        "thumb": "https://cdn.example.com/thumb.jpg",
                        "alt": "Alt text",
                    },
                    {
                        "fullsize": "https://cdn.example.com/image.jpg",
                        "alt": "Duplicate image",
                    },
                ]
            }
        }
    }

    images = embeds.embed_images(post)

    assert len(images) == 1
    assert images[0].url == "https://cdn.example.com/image.jpg"
    assert images[0].alt_text == "Alt text"
    assert images[0].thumb_url == "https://cdn.example.com/thumb.jpg"


def test_quote_record_context_is_normalized_when_available() -> None:
    post = {
        "embed": {
            "record": {
                "uri": "at://did:plc:quoted/app.bsky.feed.post/3quote",
                "author": {"handle": "quote.example"},
                "value": {
                    "text": "Quoted post text",
                    "created_at": "2026-05-06T10:00:00Z",
                },
            }
        }
    }

    quotes, warnings = embeds.quoted_posts_and_warnings(
        post,
        parse_datetime=parse_optional_datetime,
    )

    assert warnings == []
    assert quotes[0].text == "Quoted post text"
    assert quotes[0].url == "https://bsky.app/profile/quote.example/post/3quote"


def test_quote_record_missing_timestamp_is_warning_visible() -> None:
    post = {
        "embed": {
            "record": {
                "uri": "at://did:plc:quoted/app.bsky.feed.post/3quote",
                "author": {"handle": "quote.example"},
                "value": {"text": "Quoted post text"},
            }
        }
    }

    quotes, warnings = embeds.quoted_posts_and_warnings(
        post,
        parse_datetime=parse_optional_datetime,
    )

    assert quotes[0].created_at is None
    assert quotes[0].metadata["timestamp_warnings"] == ["created_at_missing"]
    assert warnings == ["created_at_missing"]


def test_unavailable_quote_record_warns_without_parsing_hidden_text() -> None:
    post = {
        "embed": {
            "record": {
                "$type": "app.bsky.feed.defs#blockedPost",
                "blocked": True,
                "uri": "at://did:plc:quoted/app.bsky.feed.post/3quote",
                "author": {"handle": "quote.example"},
                "value": {
                    "text": "Hidden quote text should not become evidence",
                    "created_at": "2026-05-06T10:00:00Z",
                },
            }
        }
    }

    quotes, warnings = embeds.quoted_posts_and_warnings(
        post,
        parse_datetime=parse_optional_datetime,
    )

    assert quotes == []
    assert warnings == ["Quoted Bluesky post is blocked."]


def test_video_embed_detection_covers_video_shapes() -> None:
    assert embeds.has_video_embed({"embed": {"$type": "app.bsky.embed.video#view"}}) is True
    assert embeds.has_video_embed({"embed": {"video": {"cid": "abc"}}}) is True
    assert (
        embeds.has_video_embed(
            {
                "embed": {
                    "playlist": "https://video.example/playlist.m3u8",
                    "thumbnail": "https://video.example/thumb.jpg",
                }
            }
        )
        is True
    )
