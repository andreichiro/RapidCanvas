from __future__ import annotations
# ruff: noqa: I001

import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from atproto import Client, models  # type: ignore[import-untyped]

from app.schemas.domain import ContextDocument as Doc, ExternalLink as Link, ImageRef as Image
from app.schemas.domain import PostContext as PContext, PostRef as PRef, ThreadPostContext as TPost

POST_URL_PATTERN = re.compile(
    r"^https://bsky\.app/profile/(?P<actor>[^/\s?#]+)/post/(?P<rkey>[^/\s?#]+)/?"
    r"(?:[?#].*)?$"
)
class BlueskyClientError(RuntimeError):
    """Raised when a Bluesky post cannot be fetched or normalized."""
class InvalidBlueskyPostUrlError(ValueError):
    """Raised when the URL is not a supported Bluesky post URL."""
def parse_post_url(url: str) -> tuple[str, str]:
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
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return datetime.now(UTC)
    return datetime.now(UTC)
def _record_text(post: Any) -> str:
    return str(_get(_get(post, "record", {}), "text", "") or "")
def _record_created_at(post: Any) -> datetime:
    record = _get(post, "record", {})
    return _parse_datetime(_get(record, "created_at", None) or _get(post, "indexed_at", None))
def _author_handle(post: Any) -> str:
    author = _get(post, "author", {})
    return str(_get(author, "handle", None) or _get(author, "did", "unknown"))
def _compact_metadata(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value not in (None, [], {})}
def _reply_ref_uri(record: Any, key: str) -> str | None:
    uri = _get(_get(_get(record, "reply", None), key, None), "uri", None)
    return str(uri) if uri else None
def _post_metadata(post: Any) -> dict[str, Any]:
    author = _get(post, "author", {})
    record = _get(post, "record", {})
    return _compact_metadata(
        {
            "at_uri": _get(post, "uri", None),
            "cid": _get(post, "cid", None),
            "indexed_at": _get(post, "indexed_at", None),
            "author_did": _get(author, "did", None),
            "author_handle": _author_handle(post),
            "author_display_name": _get(author, "display_name", None),
            "reply_root_at_uri": _reply_ref_uri(record, "root"),
            "reply_parent_at_uri": _reply_ref_uri(record, "parent"),
            "langs": _get(record, "langs", []),
            "like_count": _get(post, "like_count", None),
            "reply_count": _get(post, "reply_count", None),
            "repost_count": _get(post, "repost_count", None),
            "quote_count": _get(post, "quote_count", None),
        }
    )
def _embed_parts(post: Any) -> list[Any]:
    embed = _get(post, "embed", None)
    if embed is None:
        return []
    media = _get(embed, "media", None)
    return [embed, media] if media is not None else [embed]
def _external_links(post: Any) -> list[Link]:
    links: dict[str, Link] = {}
    for facet in _items(_get(_get(post, "record", {}), "facets", [])):
        for feature in _items(_get(facet, "features", [])):
            if uri := _get(feature, "uri", None):
                links[str(uri)] = Link(url=str(uri))
    for embed in _embed_parts(post):
        external = _get(embed, "external", None)
        if not (uri := _get(external, "uri", None)):
            continue
        url = str(uri)
        existing = links.get(url)
        links[url] = Link(
            url=url,
            title=getattr(existing, "title", None) or _optional_str(_get(external, "title", None)),
            description=getattr(existing, "description", None)
            or _optional_str(_get(external, "description", None)),
            thumb_url=getattr(existing, "thumb_url", None)
            or _optional_str(_get(external, "thumb", None)),
        )
    return list(links.values())
def _optional_str(value: Any) -> str | None:
    return str(value) if value else None
def _embed_images(post: Any) -> list[Image]:
    images: list[Image] = []
    seen_urls: set[str] = set()
    for embed in _embed_parts(post):
        for image in _items(_get(embed, "images", [])):
            fullsize = _get(image, "fullsize", None)
            thumb = _get(image, "thumb", None)
            image_url = str(fullsize or thumb or "")
            if not image_url or image_url in seen_urls:
                continue
            seen_urls.add(image_url)
            images.append(
                Image(
                    url=image_url,
                    alt_text=_optional_str(_get(image, "alt", None)),
                    thumb_url=_optional_str(thumb),
                    fullsize_url=_optional_str(fullsize),
                )
            )
    return images
def _unavailable_warning(value: Any, label: str) -> str | None:
    type_name = str(
        _get(value, "$type", None) or _get(value, "py_type", None) or _get(value, "type", "")
    ).lower()
    if _get(value, "not_found", False) or "notfound" in type_name or "not_found" in type_name:
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
def _rkey_from_at_uri(at_uri: str) -> str | None:
    parts = at_uri.split("/")
    return parts[-1] if len(parts) >= 2 and parts[-2] == "app.bsky.feed.post" else None
def _post_url(post: Any) -> str | None:
    at_uri = str(_get(post, "uri", "") or "")
    rkey = _rkey_from_at_uri(at_uri)
    if not rkey:
        return at_uri or None
    return f"https://bsky.app/profile/{_author_handle(post)}/post/{rkey}"
def _record_view_field(record_view: Any, key: str) -> Any:
    for candidate in (record_view, _get(record_view, "record", None)):
        if value := _get(candidate, key, None):
            return value
    return None
def _record_view_text(record_view: Any) -> str | None:
    candidates = [record_view, _get(record_view, "record", None)]
    for candidate in candidates:
        if text := _get(candidate, "text", None):
            return str(text)
        value = _get(candidate, "value", None)
        if text := _get(value, "text", None):
            return str(text)
        record = _get(candidate, "record", None)
        if text := _get(record, "text", None) or _get(_get(record, "value", None), "text", None):
            return str(text)
    return None
def _record_view_author(record_view: Any) -> str | None:
    author = _record_view_field(record_view, "author")
    handle = _get(author, "handle", None)
    did = _get(author, "did", None)
    return str(handle or did) if handle or did else None
def _record_view_context(record_view: Any) -> TPost | None:
    text = _record_view_text(record_view)
    if text is None:
        return None
    uri = _record_view_field(record_view, "uri")
    rkey = _rkey_from_at_uri(str(uri)) if uri else None
    author = _record_view_author(record_view)
    created_at = _get(_record_view_field(record_view, "value"), "created_at", None)
    return TPost(
        text=text,
        author=author,
        created_at=_parse_datetime(created_at) if created_at else None,
        at_uri=str(uri) if uri else None,
        url=f"https://bsky.app/profile/{author}/post/{rkey}" if author and rkey else None,
        metadata=_compact_metadata(
            {
                "at_uri": uri,
                "cid": _record_view_field(record_view, "cid"),
                "author_handle": author,
            }
        ),
    )
def _quoted_posts_and_warnings(post: Any) -> tuple[list[TPost], list[str]]:
    record_view = _get(_get(post, "embed", None), "record", None)
    if record_view is None:
        return [], []
    warning = _unavailable_warning(record_view, "Quoted Bluesky post")
    warnings = [warning] if warning else []
    context = _record_view_context(record_view)
    return ([context] if context else []), warnings
def _thread_post_context(post: Any) -> TPost | None:
    text = _record_text(post)
    if not text:
        return None
    return TPost(
        text=text,
        author=_author_handle(post),
        created_at=_record_created_at(post),
        at_uri=_get(post, "uri", None),
        url=_post_url(post),
        metadata=_post_metadata(post),
    )
def _document_metadata(post: Any) -> dict[str, Any]:
    images = _embed_images(post)
    return {
        "author": _author_handle(post),
        "at_uri": str(_get(post, "uri", "") or ""),
        "created_at": _record_created_at(post).isoformat(),
        "links": [link.url for link in _external_links(post)],
        "external_links": [link.model_dump(mode="json") for link in _external_links(post)],
        "images": [image.model_dump(mode="json") for image in images],
    }
class BlueskyClient:
    def __init__(self, client: Any | None = None) -> None:
        self._client = client or Client(base_url="https://public.api.bsky.app")
    def fetch_context(self, url: str) -> PContext:
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
        return self._normalize_thread(url, post_ref, thread_response)
    def search_posts(self, query: str, limit: int = 10) -> list[Doc]:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        try:
            response = self._client.app.bsky.feed.search_posts(
                models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
            )
        except Exception as exc:
            message = _upstream_error("Unable to search Bluesky posts", exc)
            raise BlueskyClientError(message) from exc
        documents: list[Doc] = []
        for index, post in enumerate(_items(_get(response, "posts", [])), start=1):
            url = _post_url(post) or f"bsky-search-result:{index}"
            documents.append(
                Doc(
                    id=f"BS{index}",
                    source_type="bluesky",
                    title=f"Bluesky post by {_author_handle(post)}",
                    url=url,
                    text=_record_text(post),
                    metadata=_document_metadata(post),
                )
            )
        return documents
    def _to_post_ref(self, actor: str, rkey: str) -> PRef:
        did = actor if actor.startswith("did:") else None
        if did is None:
            try:
                did = str(self._client.resolve_handle(actor).did)
            except Exception as exc:
                message = _upstream_error(f"Unable to resolve Bluesky handle {actor!r}", exc)
                raise BlueskyClientError(message) from exc
        at_uri = f"at://{did}/app.bsky.feed.post/{rkey}"
        return PRef(actor=actor, rkey=rkey, did=did, at_uri=at_uri)
    def _normalize_thread(self, url: str, post_ref: PRef, thread_response: Any) -> PContext:
        thread = _get(thread_response, "thread", thread_response)
        post = _get(thread, "post", None)
        if post is None:
            reason = _unavailable_warning(thread, "Target Bluesky post")
            raise BlueskyClientError(reason or "Bluesky thread response missing target post.")
        parent_posts, parent_warnings = self._parent_posts_and_warnings(
            _get(thread, "parent", None)
        )
        quoted_posts, quote_warnings = _quoted_posts_and_warnings(post)
        external_links = _external_links(post)
        return PContext(
            url=url,
            at_uri=post_ref.at_uri,
            author=_author_handle(post),
            text=_record_text(post),
            created_at=_record_created_at(post),
            metadata={
                **_post_metadata(post),
                "requested_actor": post_ref.actor,
                "requested_rkey": post_ref.rkey,
                "resolved_did": post_ref.did,
                "requested_at_uri": post_ref.at_uri,
            },
            parent_texts=[parent.text for parent in parent_posts],
            parent_posts=parent_posts,
            quoted_texts=[quote.text for quote in quoted_posts],
            quoted_posts=quoted_posts,
            links=[link.url for link in external_links],
            external_links=external_links,
            images=_embed_images(post),
            warnings=[*parent_warnings, *quote_warnings],
        )
    def _parent_posts_and_warnings(self, parent: Any) -> tuple[list[TPost], list[str]]:
        posts: list[TPost] = []
        warnings: list[str] = []
        current = parent
        while current is not None and len(posts) < 3:
            warning = _unavailable_warning(current, "Parent Bluesky post")
            if warning:
                warnings.append(warning)
                break
            post = _get(current, "post", None)
            context = _thread_post_context(post) if post is not None else None
            if context is not None:
                posts.append(context)
            current = _get(current, "parent", None)
        return posts, warnings
