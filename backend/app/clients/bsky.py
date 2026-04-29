"""Read-only Bluesky post fetching through the AT Protocol SDK."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from atproto import Client, models  # type: ignore[import-untyped]

from app.schemas.domain import ContextDocument, ImageRef, PostContext, PostRef

POST_URL_PATTERN = re.compile(
    r"^https://bsky\.app/profile/(?P<actor>[^/\s?#]+)/post/(?P<rkey>[^/\s?#]+)/?"
    r"(?:[?#].*)?$"
)


class BlueskyClientError(RuntimeError):
    """Raised when a Bluesky post cannot be fetched or normalized."""


class InvalidBlueskyPostUrlError(ValueError):
    """Raised when the URL is not a supported Bluesky post URL."""


def parse_post_url(url: str) -> tuple[str, str]:
    """Parse a public Bluesky post URL into actor and record key."""

    match = POST_URL_PATTERN.match(url)
    if not match:
        raise InvalidBlueskyPostUrlError("Expected https://bsky.app/profile/{actor}/post/{rkey}")
    return match.group("actor"), match.group("rkey")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _items(value: Any) -> Iterable[Any]:
    return value if isinstance(value, list | tuple) else []

def _parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)


def _record_text(post: Any) -> str:
    record = _get(post, "record", {})
    return str(_get(record, "text", "") or "")


def _record_created_at(post: Any) -> datetime:
    record = _get(post, "record", {})
    created_at = _get(record, "created_at", None) or _get(post, "indexed_at", None)
    return _parse_datetime(created_at)


def _author_handle(post: Any) -> str:
    author = _get(post, "author", {})
    return str(_get(author, "handle", None) or _get(author, "did", "unknown"))


def _facet_links(post: Any) -> list[str]:
    links: list[str] = []
    record = _get(post, "record", {})
    for facet in _items(_get(record, "facets", [])):
        for feature in _items(_get(facet, "features", [])):
            uri = _get(feature, "uri", None)
            if uri:
                links.append(str(uri))
    return links


def _dedupe(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _embed_parts(post: Any) -> list[Any]:
    embed = _get(post, "embed", None)
    if embed is None:
        return []
    media = _get(embed, "media", None)
    return [embed, media] if media is not None else [embed]


def _embed_links(post: Any) -> list[str]:
    return [
        str(uri)
        for embed in _embed_parts(post)
        if (uri := _get(_get(embed, "external", None), "uri", None))
    ]


def _links_from_post(post: Any) -> list[str]:
    return _dedupe([*_facet_links(post), *_embed_links(post)])


def _embed_images(post: Any) -> list[ImageRef]:
    images: list[ImageRef] = []
    seen_urls: set[str] = set()
    for embed in _embed_parts(post):
        for image in _items(_get(embed, "images", [])):
            url = _get(image, "fullsize", None) or _get(image, "thumb", None)
            if not url:
                continue
            image_url = str(url)
            if image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            alt_text = _get(image, "alt", None)
            normalized_alt = str(alt_text) if alt_text is not None else None
            images.append(ImageRef(url=image_url, alt_text=normalized_alt))
    return images


def _type_name(value: Any) -> str:
    type_value = _get(value, "$type", None) or _get(value, "py_type", None)
    return str(type_value or _get(value, "type", None) or "").lower()


def _unavailable_warning(value: Any, label: str) -> str | None:
    type_name = _type_name(value)
    is_not_found = (
        _get(value, "not_found", False) or "notfound" in type_name or "not_found" in type_name
    )
    if is_not_found:
        return f"{label} is unavailable or deleted."
    if _get(value, "blocked", False) or "blocked" in type_name:
        return f"{label} is blocked."
    return None


def _upstream_error(action: str, exc: Exception) -> str:
    status_code = _get(_get(exc, "response", None), "status_code", None)
    if status_code is None and exc.args:
        status_code = _get(exc.args[0], "status_code", None)
    status = f" status={status_code}" if status_code else ""
    return f"{action}: {exc.__class__.__name__}{status}"


def _record_view_text(record_view: Any) -> str | None:
    candidates = [record_view]
    nested_record = _get(record_view, "record", None)
    if nested_record is not None:
        candidates.append(nested_record)

    for candidate in candidates:
        value = _get(candidate, "value", None)
        text = _get(value, "text", None)
        if text:
            return str(text)

        record = _get(candidate, "record", None)
        record_text = _get(record, "text", None)
        if record_text:
            return str(record_text)

        nested_value = _get(record, "value", None)
        nested_text = _get(nested_value, "text", None)
        if nested_text:
            return str(nested_text)

    return None


def _quoted_texts_and_warnings(post: Any) -> tuple[list[str], list[str]]:
    embed = _get(post, "embed", None)
    record_view = _get(embed, "record", None)
    if record_view is None:
        return [], []

    warnings: list[str] = []
    warning = _unavailable_warning(record_view, "Quoted Bluesky post")
    if warning:
        warnings.append(warning)

    text = _record_view_text(record_view)
    return ([text] if text else []), warnings


def _rkey_from_at_uri(at_uri: str) -> str | None:
    parts = at_uri.split("/")
    if len(parts) < 2:
        return None
    if parts[-2] != "app.bsky.feed.post":
        return None
    return parts[-1] or None


def _post_url(post: Any) -> str | None:
    at_uri = str(_get(post, "uri", "") or "")
    rkey = _rkey_from_at_uri(at_uri)
    if rkey is None:
        return at_uri or None
    return f"https://bsky.app/profile/{_author_handle(post)}/post/{rkey}"


def _document_metadata(post: Any) -> dict[str, Any]:
    images = _embed_images(post)
    return {
        "author": _author_handle(post),
        "at_uri": str(_get(post, "uri", "") or ""),
        "created_at": _record_created_at(post).isoformat(),
        "links": _links_from_post(post),
        "images": [image.model_dump(mode="json") for image in images],
    }


class BlueskyClient:
    """Fetch and normalize public Bluesky posts."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or Client(base_url="https://public.api.bsky.app")

    def fetch_context(self, url: str) -> PostContext:
        """Fetch target post, parent context, quote context, links, and images."""

        actor, rkey = parse_post_url(url)
        post_ref = self._to_post_ref(actor, rkey)
        try:
            thread_response = self._client.get_post_thread(
                uri=post_ref.at_uri,
                depth=3,
                parent_height=2,
            )
        except Exception as exc:
            message = _upstream_error("Unable to fetch Bluesky thread", exc)
            raise BlueskyClientError(message) from exc
        return self._normalize_thread(url, post_ref.at_uri, thread_response)

    def search_posts(self, query: str, limit: int = 10) -> list[ContextDocument]:
        """Search public Bluesky posts and normalize results as context documents."""

        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            response = self._client.app.bsky.feed.search_posts(
                models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
            )
        except Exception as exc:
            message = _upstream_error("Unable to search Bluesky posts", exc)
            raise BlueskyClientError(message) from exc

        documents: list[ContextDocument] = []
        for index, post in enumerate(_items(_get(response, "posts", [])), start=1):
            url = _post_url(post) or f"bsky-search-result:{index}"
            documents.append(
                ContextDocument(
                    id=f"BS{index}",
                    source_type="bluesky",
                    title=f"Bluesky post by {_author_handle(post)}",
                    url=url,
                    text=_record_text(post),
                    metadata=_document_metadata(post),
                )
            )
        return documents

    def _to_post_ref(self, actor: str, rkey: str) -> PostRef:
        did = actor if actor.startswith("did:") else None
        if did is None:
            try:
                did = str(self._client.resolve_handle(actor).did)
            except Exception as exc:
                message = _upstream_error(f"Unable to resolve Bluesky handle {actor!r}", exc)
                raise BlueskyClientError(message) from exc
        at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        return PostRef(actor=actor, rkey=rkey, did=did, at_uri=at_uri)

    def _normalize_thread(self, url: str, at_uri: str, thread_response: Any) -> PostContext:
        thread = _get(thread_response, "thread", thread_response)
        post = _get(thread, "post", None)
        if post is None:
            reason = _unavailable_warning(thread, "Target Bluesky post")
            raise BlueskyClientError(reason or "Bluesky thread response missing target post.")

        parent_texts, parent_warnings = self._parent_texts_and_warnings(
            _get(thread, "parent", None)
        )
        quoted_texts, quote_warnings = _quoted_texts_and_warnings(post)

        return PostContext(
            url=url,
            at_uri=at_uri,
            author=_author_handle(post),
            text=_record_text(post),
            created_at=_record_created_at(post),
            parent_texts=parent_texts,
            quoted_texts=quoted_texts,
            links=_links_from_post(post),
            images=_embed_images(post),
            warnings=[*parent_warnings, *quote_warnings],
        )

    def _parent_texts_and_warnings(self, parent: Any) -> tuple[list[str], list[str]]:
        texts: list[str] = []
        warnings: list[str] = []
        current = parent
        while current is not None and len(texts) < 3:
            warning = _unavailable_warning(current, "Parent Bluesky post")
            if warning:
                warnings.append(warning)
                break
            post = _get(current, "post", None)
            text = _record_text(post) if post is not None else ""
            if text:
                texts.append(text)
            current = _get(current, "parent", None)
        return texts, warnings
