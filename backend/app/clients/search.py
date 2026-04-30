"""Search providers for Bluesky and public web context."""

from __future__ import annotations

import hashlib
import importlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.clients.fetcher import LinkedPageFetcher, validate_public_http_url
from app.guardrails.prompt_injection import sanitize_context_document
from app.schemas.domain import ContextDocument


class SearchProvider(Protocol):
    """Async search provider boundary used by the retrieval lane."""

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        """Return untrusted context documents for a query."""


@dataclass(frozen=True)
class SearchBundle:
    """Search documents plus non-fatal warnings for trace propagation."""

    documents: list[ContextDocument]
    warnings: list[str]


class BlueskySearchProvider:
    """Read-only Bluesky post search adapter."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client or self._default_client()
        self.last_warnings: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        """Search public Bluesky posts and normalize them into context documents."""

        self.last_warnings = []
        if not query.strip():
            return []
        try:
            posts = self._search_posts(query=query, limit=limit)
        except Exception as exc:
            self.last_warnings.append(f"bluesky_search_failed:{exc.__class__.__name__}")
            return []

        documents: list[ContextDocument] = []
        for index, post in enumerate(posts[:limit], start=1):
            document = _document_from_bluesky_search_item(post, query=query, index=index)
            if document is None:
                continue
            sanitized, scan = sanitize_context_document(document)
            if scan.is_risky:
                self.last_warnings.append(f"prompt_injection_risk:{sanitized.id}")
            documents.append(sanitized)
        return documents

    def _search_posts(self, query: str, limit: int) -> list[Any]:
        direct_search = getattr(self._client, "search_posts", None)
        if callable(direct_search):
            response = direct_search(query, limit)
        else:
            models = importlib.import_module("atproto").models
            params = models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
            response = self._client.app.bsky.feed.search_posts(params)
        posts = _get(response, "posts", response)
        return list(_items(posts))

    def _default_client(self) -> Any:
        atproto = importlib.import_module("atproto")
        return atproto.Client(base_url="https://public.api.bsky.app")


class WebSearchProvider:
    """DDGS-backed web search adapter with safe page fetching."""

    def __init__(
        self,
        *,
        fetcher: LinkedPageFetcher | None = None,
        ddgs_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._fetcher = fetcher or LinkedPageFetcher()
        self._ddgs_factory = ddgs_factory or self._default_ddgs_factory
        self.last_warnings: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        """Search the web, fetch public result pages, and return extracted documents."""

        self.last_warnings = []
        if not query.strip():
            return []
        hits = self._search_hits(query=query, limit=limit)
        documents: list[ContextDocument] = []
        for index, hit in enumerate(hits[:limit], start=1):
            document = await self._document_from_hit(hit, query=query, index=index)
            if document is not None:
                documents.append(document)
        return documents

    async def _document_from_hit(
        self,
        hit: dict[str, Any],
        *,
        query: str,
        index: int,
    ) -> ContextDocument | None:
        url = str(hit.get("href") or hit.get("url") or "")
        if not url:
            self.last_warnings.append(f"web_search_missing_url:{index}")
            return None
        safety = validate_public_http_url(url, resolver=self._fetcher.resolver)
        if not safety.allowed:
            self.last_warnings.extend(safety.warnings)
            return None

        result = await self._fetcher.fetch(url, source_id=f"WEB-{_stable_hash(url)[:12]}")
        self.last_warnings.extend(result.warnings)
        if result.document is None:
            if result.blocked:
                return None
            return self._fallback_document(hit, query=query, index=index)
        return _merge_search_hit_metadata(result.document, hit, query=query, index=index)

    def _search_hits(self, query: str, limit: int) -> list[dict[str, Any]]:
        try:
            ddgs = self._ddgs_factory()
            if hasattr(ddgs, "__enter__") and hasattr(ddgs, "__exit__"):
                with ddgs as active_ddgs:
                    return list(active_ddgs.text(query, max_results=limit))
            return list(ddgs.text(query, max_results=limit))
        except Exception as exc:
            self.last_warnings.append(f"web_search_failed:{exc.__class__.__name__}")
            return []

    def _fallback_document(
        self,
        hit: dict[str, Any],
        *,
        query: str,
        index: int,
    ) -> ContextDocument | None:
        url = str(hit.get("href") or hit.get("url") or "")
        snippet = str(hit.get("body") or hit.get("snippet") or "")
        if not url or not snippet:
            return None
        document = ContextDocument(
            id=f"WEB-{_stable_hash(url)[:12]}",
            source_type="web",
            title=str(hit.get("title") or url),
            url=url,
            text=snippet,
            metadata={"rank": index, "search_query": query, "fetch_fallback": True},
        )
        sanitized, scan = sanitize_context_document(document)
        if scan.is_risky:
            self.last_warnings.append(f"prompt_injection_risk:{sanitized.id}")
        return sanitized

    def _default_ddgs_factory(self) -> Any:
        ddgs_module = importlib.import_module("ddgs")
        return ddgs_module.DDGS()


async def collect_search_context(
    query: str,
    providers: list[SearchProvider],
    limit_per_provider: int = 5,
) -> SearchBundle:
    """Collect context from providers while preserving non-fatal provider warnings."""

    documents: list[ContextDocument] = []
    warnings: list[str] = []
    for provider in providers:
        provider_documents = await provider.search(query, limit=limit_per_provider)
        documents.extend(provider_documents)
        provider_warnings = getattr(provider, "last_warnings", [])
        warnings.extend(str(warning) for warning in provider_warnings)
    return SearchBundle(documents=documents, warnings=warnings)


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _merge_search_hit_metadata(
    document: ContextDocument,
    hit: dict[str, Any],
    *,
    query: str,
    index: int,
) -> ContextDocument:
    title = str(hit.get("title") or document.title)
    metadata = {
        **document.metadata,
        "rank": index,
        "search_query": query,
        "search_snippet": str(hit.get("body") or hit.get("snippet") or ""),
    }
    return document.model_copy(update={"title": title, "metadata": metadata})


def _document_from_bluesky_search_item(
    post: Any,
    *,
    query: str,
    index: int,
) -> ContextDocument | None:
    if isinstance(post, ContextDocument):
        metadata = {
            **post.metadata,
            "rank": index,
            "search_query": query,
        }
        return post.model_copy(update={"metadata": metadata})

    text = _post_text(post)
    if not text:
        return None
    uri = str(_get(post, "uri", "") or "")
    author = _author_handle(post)
    return ContextDocument(
        id=f"BSKY-{_stable_hash(uri or text)[:12]}",
        source_type="bluesky",
        title=f"Bluesky search result by {author}",
        url=_post_url(post, fallback_uri=uri),
        text=text,
        metadata={
            "rank": index,
            "at_uri": uri,
            "author": author,
            "search_query": query,
        },
    )


def _items(value: Any) -> Iterable[Any]:
    if value is None:
        return []
    if isinstance(value, list | tuple):
        return value
    return []


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _post_text(post: Any) -> str:
    record = _get(post, "record", {})
    return str(_get(record, "text", "") or _get(post, "text", "") or "")


def _author_handle(post: Any) -> str:
    author = _get(post, "author", {})
    return str(_get(author, "handle", None) or _get(author, "did", "unknown"))


def _post_url(post: Any, fallback_uri: str) -> str:
    author = _author_handle(post)
    uri = fallback_uri or str(_get(post, "uri", ""))
    rkey = uri.rsplit("/", maxsplit=1)[-1] if "/" in uri else ""
    if author != "unknown" and rkey:
        return f"https://bsky.app/profile/{author}/post/{rkey}"
    return uri or "https://bsky.app"
