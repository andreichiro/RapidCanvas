"""Read-only Bluesky post fetching through the AT Protocol SDK."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from atproto import Client  # type: ignore[import-untyped]

from app.schemas.domain import ImageRef, PostContext, PostRef

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
        raise InvalidBlueskyPostUrlError(
            "Expected https://bsky.app/profile/{actor}/post/{rkey}"
        )
    return match.group("actor"), match.group("rkey")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _items(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return value
    return []


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
    return _parse_datetime(_get(record, "created_at", None) or _get(post, "indexed_at", None))


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


def _embed_images(post: Any) -> list[ImageRef]:
    images: list[ImageRef] = []
    embed = _get(post, "embed", None)
    for image in _items(_get(embed, "images", [])):
        url = _get(image, "fullsize", None) or _get(image, "thumb", None)
        if url:
            images.append(ImageRef(url=str(url), alt_text=_get(image, "alt", None)))
    return images


def _quoted_text(post: Any) -> str | None:
    embed = _get(post, "embed", None)
    record_view = _get(embed, "record", None)
    record = _get(record_view, "record", None)
    value = _get(record, "value", None)
    text = _get(value, "text", None)
    return str(text) if text else None


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
            raise BlueskyClientError(f"Unable to fetch Bluesky thread: {exc}") from exc
        return self._normalize_thread(url, post_ref.at_uri, thread_response)

    def _to_post_ref(self, actor: str, rkey: str) -> PostRef:
        did = actor if actor.startswith("did:") else None
        if did is None:
            try:
                did = str(self._client.resolve_handle(actor).did)
            except Exception as exc:
                message = f"Unable to resolve Bluesky handle {actor!r}: {exc}"
                raise BlueskyClientError(message) from exc
        at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        return PostRef(actor=actor, rkey=rkey, did=did, at_uri=at_uri)

    def _normalize_thread(self, url: str, at_uri: str, thread_response: Any) -> PostContext:
        thread = _get(thread_response, "thread", thread_response)
        post = _get(thread, "post", None)
        if post is None:
            raise BlueskyClientError("Bluesky thread response did not include a target post.")

        parent_texts = self._parent_texts(_get(thread, "parent", None))
        quoted = _quoted_text(post)
        quoted_texts = [quoted] if quoted else []

        return PostContext(
            url=url,
            at_uri=at_uri,
            author=_author_handle(post),
            text=_record_text(post),
            created_at=_record_created_at(post),
            parent_texts=parent_texts,
            quoted_texts=quoted_texts,
            links=_facet_links(post),
            images=_embed_images(post),
        )

    def _parent_texts(self, parent: Any) -> list[str]:
        texts: list[str] = []
        current = parent
        while current is not None and len(texts) < 3:
            post = _get(current, "post", None)
            text = _record_text(post) if post is not None else ""
            if text:
                texts.append(text)
            current = _get(current, "parent", None)
        return texts
