from __future__ import annotations

from typing import Any

from atproto import Client, models  # type: ignore[import-untyped]

from app.clients.bsky_embeds import get_value, items
from app.clients.bsky_normalize import normalize_thread, search_document
from app.clients.bsky_url import (
    InvalidBlueskyPostUrlError,
    is_did,
    parse_post_url,
    post_ref_for_did,
)
from app.schemas.domain import ContextDocument, PostContext, PostRef

__all__ = [
    "BlueskyClient",
    "BlueskyClientError",
    "InvalidBlueskyPostUrlError",
    "parse_post_url",
]


class BlueskyClientError(RuntimeError):
    """Raised when a Bluesky post cannot be fetched or normalized."""


class BlueskyClient:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client or Client(base_url="https://public.api.bsky.app")

    def fetch_context(self, url: str) -> PostContext:
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
        try:
            return normalize_thread(url, post_ref, thread_response)
        except ValueError as exc:
            raise BlueskyClientError(str(exc)) from exc

    def search_posts(self, query: str, limit: int = 10) -> list[ContextDocument]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            response = self._client.app.bsky.feed.search_posts(
                models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
            )
        except Exception as exc:
            message = _upstream_error("Unable to search Bluesky posts", exc)
            raise BlueskyClientError(message) from exc
        return [
            search_document(post, index=index)
            for index, post in enumerate(items(get_value(response, "posts", [])), start=1)
        ]

    def _to_post_ref(self, actor: str, rkey: str) -> PostRef:
        if is_did(actor):
            return post_ref_for_did(actor, rkey, actor)
        try:
            did = str(self._client.resolve_handle(actor).did)
        except Exception as exc:
            message = _upstream_error(f"Unable to resolve Bluesky handle {actor!r}", exc)
            raise BlueskyClientError(message) from exc
        return post_ref_for_did(actor, rkey, did)


def _upstream_error(action: str, exc: Exception) -> str:
    status_code = get_value(get_value(exc, "response", None), "status_code", None)
    if status_code is None and exc.args:
        status_code = get_value(exc.args[0], "status_code", None)
    status = f" status={status_code}" if status_code else ""
    return f"{action}: {exc.__class__.__name__}{status}"
