from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.clients import bsky_embeds as embeds
from app.schemas.domain import (
    ContextDocument,
    PostContext,
    PostRef,
    ThreadPostContext,
)

DETERMINISTIC_TIMESTAMP_FALLBACK = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class TimestampResult:
    value: datetime
    warnings: list[str]
    source: str


def normalize_thread(url: str, post_ref: PostRef, thread_response: Any) -> PostContext:
    thread = embeds.get_value(thread_response, "thread", thread_response)
    post = embeds.get_value(thread, "post", None)
    if post is None:
        reason = embeds.unavailable_warning(thread, "Target Bluesky post")
        raise ValueError(reason or "Bluesky thread response missing target post.")
    timestamp = record_created_at(post)
    has_video = embeds.has_video_embed(post)
    parent_posts, parent_warnings = parent_posts_and_warnings(embeds.get_value(thread, "parent"))
    quoted_posts, quote_warnings = embeds.quoted_posts_and_warnings(
        post,
        parse_datetime=parse_optional_datetime,
    )
    external_links = embeds.external_links(post)
    warnings = [
        *timestamp.warnings,
        *parent_warnings,
        *quote_warnings,
        *video_warnings(has_video),
    ]
    return PostContext(
        url=url,
        at_uri=post_ref.at_uri,
        author=author_handle(post),
        text=record_text(post),
        created_at=timestamp.value,
        metadata={
            **post_metadata(post),
            "requested_actor": post_ref.actor,
            "requested_rkey": post_ref.rkey,
            "resolved_did": post_ref.did,
            "requested_at_uri": post_ref.at_uri,
            "created_at_source": timestamp.source,
            "timestamp_warnings": timestamp.warnings,
            "has_unparsed_video": has_video,
            "unsupported_media": ["video"] if has_video else [],
        },
        parent_texts=[parent.text for parent in parent_posts],
        parent_posts=parent_posts,
        quoted_texts=[quote.text for quote in quoted_posts],
        quoted_posts=quoted_posts,
        links=[link.url for link in external_links],
        external_links=external_links,
        images=embeds.embed_images(post),
        warnings=warnings,
    )


def search_document(post: Any, *, index: int) -> ContextDocument:
    url = embeds.post_url(post, author_handle(post)) or f"bsky-search-result:{index}"
    return ContextDocument(
        id=f"BS{index}",
        source_type="bluesky",
        title=f"Bluesky post by {author_handle(post)}",
        url=url,
        text=record_text(post),
        metadata=document_metadata(post),
    )


def record_text(post: Any) -> str:
    return str(embeds.get_value(embeds.get_value(post, "record", {}), "text", "") or "")


def record_created_at(post: Any) -> TimestampResult:
    record = embeds.get_value(post, "record", {})
    created_at_raw = embeds.get_value(record, "created_at", None)
    indexed_at_raw = embeds.get_value(post, "indexed_at", None)
    created_at = parse_datetime(created_at_raw)
    if created_at is not None:
        return TimestampResult(created_at, [], "created_at")
    indexed_at = parse_datetime(indexed_at_raw)
    if indexed_at is not None:
        warning = (
            "created_at_missing" if created_at_raw in (None, "") else "created_at_parse_failed"
        )
        return TimestampResult(indexed_at, [warning], "indexed_at")
    warning = "created_at_missing" if created_at_raw in (None, "") else "created_at_parse_failed"
    return TimestampResult(
        DETERMINISTIC_TIMESTAMP_FALLBACK,
        [warning],
        "deterministic_fallback",
    )


def parse_optional_datetime(value: Any) -> tuple[datetime | None, list[str]]:
    if value in (None, ""):
        return None, ["created_at_missing"]
    parsed = parse_datetime(value)
    if parsed is None:
        return None, ["created_at_parse_failed"]
    return parsed, []


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def author_handle(post: Any) -> str:
    author = embeds.get_value(post, "author", {})
    return str(
        embeds.get_value(author, "handle", None) or embeds.get_value(author, "did", "unknown")
    )


def post_metadata(post: Any) -> dict[str, Any]:
    author = embeds.get_value(post, "author", {})
    record = embeds.get_value(post, "record", {})
    timestamp = record_created_at(post)
    return embeds.compact_metadata(
        {
            "at_uri": embeds.get_value(post, "uri", None),
            "cid": embeds.get_value(post, "cid", None),
            "indexed_at": embeds.get_value(post, "indexed_at", None),
            "author_did": embeds.get_value(author, "did", None),
            "author_handle": author_handle(post),
            "author_display_name": embeds.get_value(author, "display_name", None),
            "reply_root_at_uri": reply_ref_uri(record, "root"),
            "reply_parent_at_uri": reply_ref_uri(record, "parent"),
            "langs": embeds.get_value(record, "langs", []),
            "like_count": embeds.get_value(post, "like_count", None),
            "reply_count": embeds.get_value(post, "reply_count", None),
            "repost_count": embeds.get_value(post, "repost_count", None),
            "quote_count": embeds.get_value(post, "quote_count", None),
            "created_at_source": timestamp.source,
            "timestamp_warnings": timestamp.warnings,
        }
    )


def document_metadata(post: Any) -> dict[str, Any]:
    images = embeds.embed_images(post)
    timestamp = record_created_at(post)
    return {
        "author": author_handle(post),
        "at_uri": str(embeds.get_value(post, "uri", "") or ""),
        "created_at": timestamp.value.isoformat(),
        "created_at_source": timestamp.source,
        "timestamp_warnings": timestamp.warnings,
        "links": [link.url for link in embeds.external_links(post)],
        "external_links": [link.model_dump(mode="json") for link in embeds.external_links(post)],
        "images": [image.model_dump(mode="json") for image in images],
    }


def reply_ref_uri(record: Any, key: str) -> str | None:
    uri = embeds.get_value(embeds.get_value(embeds.get_value(record, "reply", None), key), "uri")
    return str(uri) if uri else None


def thread_post_context(post: Any) -> tuple[ThreadPostContext | None, list[str]]:
    text = record_text(post)
    if not text:
        return None, []
    timestamp = record_created_at(post)
    return (
        ThreadPostContext(
            text=text,
            author=author_handle(post),
            created_at=timestamp.value,
            at_uri=embeds.get_value(post, "uri", None),
            url=embeds.post_url(post, author_handle(post)),
            metadata=post_metadata(post),
        ),
        timestamp.warnings,
    )


def parent_posts_and_warnings(parent: Any) -> tuple[list[ThreadPostContext], list[str]]:
    posts: list[ThreadPostContext] = []
    warnings: list[str] = []
    current = parent
    while current is not None and len(posts) < 3:
        warning = embeds.unavailable_warning(current, "Parent Bluesky post")
        if warning:
            warnings.append(warning)
            break
        post = embeds.get_value(current, "post", None)
        context, context_warnings = thread_post_context(post) if post is not None else (None, [])
        warnings.extend(context_warnings)
        if context is not None:
            posts.append(context)
        current = embeds.get_value(current, "parent", None)
    return posts, warnings


def video_warnings(has_video: bool) -> list[str]:
    return (
        [
            "video_embed_unparsed: the post contains video, and this build uses the post "
            "text/thread/link/image evidence without parsing video frames."
        ]
        if has_video
        else []
    )
