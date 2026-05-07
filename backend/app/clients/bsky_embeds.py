from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from app.clients.bsky_url import post_url_for_author, rkey_from_at_uri
from app.schemas.domain import ExternalLink, ImageRef, ThreadPostContext


def get_value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list | tuple) else []


def compact_metadata(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, [], {})}


def optional_str(value: Any) -> str | None:
    return str(value) if value else None


def embed_parts(post: Any) -> list[Any]:
    embed = get_value(post, "embed", None)
    if embed is None:
        return []
    media = get_value(embed, "media", None)
    return [embed, media] if media is not None else [embed]


def type_name(value: Any) -> str:
    return str(
        get_value(value, "$type", None)
        or get_value(value, "py_type", None)
        or get_value(value, "type", "")
    ).lower()


def unavailable_warning(value: Any, label: str) -> str | None:
    name = type_name(value)
    if get_value(value, "not_found", False) or "notfound" in name or "not_found" in name:
        return f"{label} is unavailable or deleted."
    if get_value(value, "blocked", False) or "blocked" in name:
        return f"{label} is blocked."
    return None


def is_video_embed(value: Any) -> bool:
    name = type_name(value)
    if "app.bsky.embed.video" in name or "embed.video" in name:
        return True
    if get_value(value, "video", None) is not None:
        return True
    return bool(
        get_value(value, "playlist", None)
        and (get_value(value, "thumbnail", None) or get_value(value, "cid", None))
    )


def has_video_embed(post: Any) -> bool:
    return any(is_video_embed(embed) for embed in embed_parts(post))


def external_links(post: Any) -> list[ExternalLink]:
    links: dict[str, ExternalLink] = {}
    for facet in items(get_value(get_value(post, "record", {}), "facets", [])):
        for feature in items(get_value(facet, "features", [])):
            if uri := get_value(feature, "uri", None):
                links[str(uri)] = ExternalLink(url=str(uri))
    for embed in embed_parts(post):
        external = get_value(embed, "external", None)
        if not (uri := get_value(external, "uri", None)):
            continue
        url = str(uri)
        existing = links.get(url)
        links[url] = ExternalLink(
            url=url,
            title=getattr(existing, "title", None) or optional_str(get_value(external, "title")),
            description=getattr(existing, "description", None)
            or optional_str(get_value(external, "description")),
            thumb_url=getattr(existing, "thumb_url", None)
            or optional_str(get_value(external, "thumb")),
        )
    return list(links.values())


def embed_images(post: Any) -> list[ImageRef]:
    images: list[ImageRef] = []
    seen_urls: set[str] = set()
    for embed in embed_parts(post):
        for image in items(get_value(embed, "images", [])):
            fullsize = get_value(image, "fullsize", None)
            thumb = get_value(image, "thumb", None)
            image_url = str(fullsize or thumb or "")
            if not image_url or image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            images.append(
                ImageRef(
                    url=image_url,
                    alt_text=optional_str(get_value(image, "alt", None)),
                    thumb_url=optional_str(thumb),
                    fullsize_url=optional_str(fullsize),
                )
            )
    return images


def quoted_posts_and_warnings(
    post: Any,
    *,
    parse_datetime: Callable[[Any], tuple[datetime | None, list[str]]],
) -> tuple[list[ThreadPostContext], list[str]]:
    record_view = get_value(get_value(post, "embed", None), "record", None)
    if record_view is None:
        return [], []
    warning = unavailable_warning(record_view, "Quoted Bluesky post")
    if warning:
        return [], [warning]
    warnings: list[str] = []
    context, context_warnings = record_view_context(record_view, parse_datetime=parse_datetime)
    warnings.extend(context_warnings)
    return ([context] if context else []), warnings


def record_view_context(
    record_view: Any,
    *,
    parse_datetime: Callable[[Any], tuple[datetime | None, list[str]]],
) -> tuple[ThreadPostContext | None, list[str]]:
    text = record_view_text(record_view)
    if text is None:
        return None, []
    uri = record_view_field(record_view, "uri")
    rkey = rkey_from_at_uri(str(uri)) if uri else None
    author = record_view_author(record_view)
    created_at_raw = get_value(record_view_field(record_view, "value"), "created_at", None)
    created_at, warnings = parse_datetime(created_at_raw)
    return (
        ThreadPostContext(
            text=text,
            author=author,
            created_at=created_at,
            at_uri=str(uri) if uri else None,
            url=f"https://bsky.app/profile/{author}/post/{rkey}" if author and rkey else None,
            metadata=compact_metadata(
                {
                    "at_uri": uri,
                    "cid": record_view_field(record_view, "cid"),
                    "author_handle": author,
                    "timestamp_warnings": warnings,
                }
            ),
        ),
        warnings,
    )


def record_view_field(record_view: Any, key: str) -> Any:
    for candidate in (record_view, get_value(record_view, "record", None)):
        if value := get_value(candidate, key, None):
            return value
    return None


def record_view_text(record_view: Any) -> str | None:
    candidates = [record_view, get_value(record_view, "record", None)]
    for candidate in candidates:
        if text := get_value(candidate, "text", None):
            return str(text)
        value = get_value(candidate, "value", None)
        if text := get_value(value, "text", None):
            return str(text)
        record = get_value(candidate, "record", None)
        if text := get_value(record, "text", None) or get_value(
            get_value(record, "value", None), "text", None
        ):
            return str(text)
    return None


def record_view_author(record_view: Any) -> str | None:
    author = record_view_field(record_view, "author")
    handle = get_value(author, "handle", None)
    did = get_value(author, "did", None)
    return str(handle or did) if handle or did else None


def post_url(post: Any, author_handle: str) -> str | None:
    at_uri = str(get_value(post, "uri", "") or "")
    return post_url_for_author(author_handle, at_uri)
