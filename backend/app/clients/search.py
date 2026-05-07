"""Search providers for Bluesky and public web context."""

from __future__ import annotations

import importlib
from collections.abc import Callable, Mapping
from itertools import islice
from typing import Any
from urllib.parse import urlparse

from app.clients import search_support as ss
from app.clients.extraction import (
    Resolver,
    default_resolver,
    sanitize_search_hit_document,
    validate_public_http_url,
)
from app.clients.fetcher import LinkedPageFetcher
from app.clients.search_collect import (
    SearchBundle,
    SearchProvider,
    SearchProviderWithWarnings,
    collect_search_context,
)
from app.guardrails.prompt_injection import sanitize_context_document
from app.ml.boundary import boundary_attr as ba
from app.ml.boundary import boundary_text, safe_limit
from app.schemas.domain import ContextDocument

__all__ = [
    "BlueskySearchProvider",
    "SearchBundle",
    "SearchProvider",
    "SearchProviderWithWarnings",
    "WebSearchProvider",
    "collect_search_context",
]


class BlueskySearchProvider:
    def __init__(
        self,
        client: Any | None = None,
        resolver: Resolver = default_resolver,
    ) -> None:
        self._client = client or self._default_client()
        self._resolver = resolver
        self.last_warnings = ss.WarningState()

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        return (await self.search_with_warnings(query, limit=limit)).documents

    async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
        warnings: list[str] = []
        provider_limit = safe_limit(limit)
        query_text = boundary_text(query, "search_query_text_failed")
        if not query_text.strip() or provider_limit == 0:
            return self._search_bundle([], warnings)
        try:
            posts = self._search_posts(query=query_text, limit=provider_limit)
        except Exception as exc:
            warnings.append(f"bluesky_search_failed:{exc.__class__.__name__}")
            return self._search_bundle([], warnings)
        documents: list[ContextDocument] = []
        for index, post in enumerate(posts[:provider_limit], start=1):
            document = self._document_from_post(
                post, query=query_text, index=index, warnings=warnings
            )
            if document is not None:
                documents.append(document)
        return self._search_bundle(documents, warnings)

    def _document_from_post(
        self,
        post: object,
        *,
        query: str,
        index: int,
        warnings: list[str],
    ) -> ContextDocument | None:
        try:
            document = _document_from_bluesky_search_item(post, query=query, index=index)
        except Exception as exc:
            warnings.append(f"bluesky_search_invalid_item:{index}:{exc.__class__.__name__}")
            return None
        if document is None:
            return None
        if url_warnings := ss.blocked_document_url_warnings(document, resolver=self._resolver):
            url = ba(document, "url", "document_url_field_failed")
            warnings.append(ss.blocked_url_warning(url, url_warnings))
            warnings.extend(url_warnings)
            return None
        sanitized, scan = sanitize_context_document(document)
        if scan.is_risky:
            warnings.append(f"prompt_injection_risk:{sanitized.id}")
        return sanitized

    def _search_bundle(self, documents: list[ContextDocument], warnings: list[str]) -> SearchBundle:
        self.last_warnings.set(warnings)
        return SearchBundle(documents=documents, warnings=list(warnings))

    def _search_posts(self, query: str, limit: int) -> list[Any]:
        direct_search = getattr(self._client, "search_posts", None)
        if callable(direct_search):
            response = direct_search(query, limit)
        else:
            models = importlib.import_module("atproto").models
            params = models.AppBskyFeedSearchPosts.Params(q=query, limit=limit, sort="top")
            response = self._client.app.bsky.feed.search_posts(params)
        posts = ss.get_value(response, "posts", response)
        return list(islice(ss.items(posts), safe_limit(limit)))

    def _default_client(self) -> Any:
        atproto = importlib.import_module("atproto")
        return atproto.Client(base_url="https://public.api.bsky.app")


class WebSearchProvider:
    def __init__(
        self,
        *,
        fetcher: LinkedPageFetcher | None = None,
        ddgs_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._fetcher = fetcher or LinkedPageFetcher()
        self._ddgs_factory = ddgs_factory or self._default_ddgs_factory
        self.last_warnings = ss.WarningState()

    async def search(self, query: str, limit: int = 5) -> list[ContextDocument]:
        return (await self.search_with_warnings(query, limit=limit)).documents

    async def search_with_warnings(self, query: str, limit: int = 5) -> SearchBundle:
        warnings: list[str] = []
        provider_limit = safe_limit(limit)
        query_text = boundary_text(query, "search_query_text_failed")
        if not query_text.strip() or provider_limit == 0:
            return self._search_bundle([], warnings)
        hits = self._search_hits(query=query_text, limit=provider_limit, warnings=warnings)
        documents: list[ContextDocument] = []
        for index, hit in enumerate(hits[:provider_limit], start=1):
            try:
                document = await self._document_from_hit(
                    hit, query=query_text, index=index, warnings=warnings
                )
            except Exception as exc:
                warnings.append(f"web_search_invalid_hit:{index}:{exc.__class__.__name__}")
                continue
            if document is not None:
                documents.append(document)
        return self._search_bundle(documents, warnings)

    async def _document_from_hit(
        self,
        hit: object,
        *,
        query: str,
        index: int,
        warnings: list[str],
    ) -> ContextDocument | None:
        if not isinstance(hit, dict):
            warnings.append(f"web_search_invalid_hit:{index}")
            return None
        url = boundary_text(hit.get("href") or hit.get("url") or "")
        if not url:
            warnings.append(f"web_search_missing_url:{index}")
            return None
        safety = validate_public_http_url(url, resolver=self._fetcher.resolver)
        if not safety.allowed:
            self._record_blocked_url(url, safety.warnings, warnings)
            return None

        result = await self._fetcher.fetch(url, source_id=f"WEB-{ss.stable_hash(url)[:12]}")
        if result.document is None:
            if result.blocked:
                self._record_blocked_url(url, result.warnings, warnings)
                return None
            warnings.extend(result.warnings)
            return self._fallback_document(
                hit,
                query=query,
                index=index,
                warnings=warnings,
                fetch_status=result.status_code,
                fetch_warnings=result.warnings,
            )
        warnings.extend(result.warnings)
        sanitized, scan = sanitize_search_hit_document(
            result.document,
            hit,
            query=query,
            index=index,
            fetch_status=result.status_code,
        )
        if scan.is_risky:
            warnings.append(f"prompt_injection_risk:{sanitized.id}")
        return sanitized

    def _record_blocked_url(self, url: str, reasons: tuple[str, ...], warnings: list[str]) -> None:
        warnings.append(ss.blocked_url_warning(url, reasons))
        warnings.extend(reasons)

    def _search_hits(self, query: str, limit: int, warnings: list[str]) -> list[dict[str, Any]]:
        try:
            ddgs = self._ddgs_factory()
            if hasattr(ddgs, "__enter__") and hasattr(ddgs, "__exit__"):
                with ddgs as active_ddgs:
                    return list(islice(active_ddgs.text(query, max_results=limit), limit))
            return list(islice(ddgs.text(query, max_results=limit), limit))
        except Exception as exc:
            warnings.append(f"web_search_failed:{exc.__class__.__name__}")
            return []

    def _fallback_document(
        self,
        hit: dict[str, Any],
        *,
        query: str,
        index: int,
        warnings: list[str],
        fetch_status: int | None,
        fetch_warnings: tuple[str, ...] = (),
    ) -> ContextDocument | None:
        url = boundary_text(hit.get("href") or hit.get("url") or "")
        snippet = boundary_text(hit.get("body") or hit.get("snippet") or "")
        if not url or not snippet:
            return None
        document = ContextDocument(
            id=f"WEB-{ss.stable_hash(url)[:12]}",
            source_type="web",
            title=url,
            url=url,
            text="",
            metadata={},
        )
        sanitized, scan = sanitize_search_hit_document(
            document,
            hit,
            query=query,
            index=index,
            fetch_fallback=True,
            fetch_status=fetch_status,
        )
        sanitized = _with_fetch_warning_metadata(sanitized, fetch_warnings)
        if scan.is_risky:
            warnings.append(f"prompt_injection_risk:{sanitized.id}")
        return sanitized

    def _search_bundle(self, documents: list[ContextDocument], warnings: list[str]) -> SearchBundle:
        self.last_warnings.set(warnings)
        return SearchBundle(documents=documents, warnings=list(warnings))

    def _default_ddgs_factory(self) -> Any:
        ddgs_module = importlib.import_module("ddgs")
        return ddgs_module.DDGS()


def _document_from_bluesky_search_item(
    post: Any, *, query: str, index: int
) -> ContextDocument | None:
    if isinstance(post, ContextDocument):
        url = ba(post, "url", "document_url_field_failed")
        url_text = boundary_text(url, "document_url_text_failed")
        metadata = {
            **_metadata_mapping(post.metadata),
            "provider": "bluesky_search",
            "query": query,
            "rank": index,
            "domain": _canonical_domain(url_text),
            "search_query": query,
            "snippet_only": False,
            "fetch_success": True,
            "fetch_status": 200,
        }
        return post.model_copy(update={"url": url, "metadata": metadata})
    text = ss.post_text(post)
    if not text:
        return None
    uri = boundary_text(ss.get_value(post, "uri", "") or "")
    author = ss.author_handle(post)
    return ContextDocument(
        id=f"BSKY-{ss.stable_hash(uri or text)[:12]}",
        source_type="bluesky",
        title=f"Bluesky search result by {author}",
        url=ss.post_url(post, fallback_uri=uri),
        text=text,
        metadata={
            "provider": "bluesky_search",
            "query": query,
            "rank": index,
            "domain": "bsky.app",
            "at_uri": uri,
            "author": author,
            "search_query": query,
            "snippet_only": False,
            "fetch_success": True,
            "fetch_status": 200,
        },
    )


def _metadata_mapping(value: object) -> dict[str, object]:
    if isinstance(value, Mapping):
        try:
            return dict(value)
        except Exception as exc:
            return {"metadata_iter_failed": f"metadata_iter_failed:{exc.__class__.__name__}"}
    return {"metadata": value}


def _canonical_domain(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _with_fetch_warning_metadata(
    document: ContextDocument,
    fetch_warnings: tuple[str, ...],
) -> ContextDocument:
    if not fetch_warnings:
        return document
    metadata = dict(document.metadata)
    existing = metadata.get("warnings")
    warning_values = list(existing) if isinstance(existing, list) else []
    for warning in fetch_warnings:
        if warning not in warning_values:
            warning_values.append(warning)
    metadata["warnings"] = warning_values
    metadata["fetch_warnings"] = list(fetch_warnings)
    if "robots_disallowed" in fetch_warnings:
        metadata["robots_disallowed"] = True
        metadata["fetch_status"] = "robots_disallowed"
        metadata["fetch_status_reason"] = "robots_disallowed"
    return document.model_copy(update={"metadata": metadata})
