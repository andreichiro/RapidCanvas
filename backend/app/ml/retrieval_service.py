from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import app.ml.vector_store as vs
from app.clients import search as sc
from app.clients.bsky import BlueskyClient
from app.clients.extraction import redact_url_for_warning, validate_source_url_metadata
from app.clients.fetcher import LinkedPageFetcher
from app.clients.search_support import warning_strings
from app.config import Settings, get_settings
from app.guardrails.identifiers import safe_identifier
from app.guardrails.prompt_injection import PromptInjectionScanner, sanitize_context_documents
from app.ml import diagnostics as d
from app.ml.boundary import boundary_attr as ba
from app.ml.boundary import boundary_text, bounded_items, safe_limit
from app.ml.c2_policy import unique_documents_by_id
from app.ml.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider, text_hash
from app.ml.rag_boundary import safe_last_diagnostics
from app.ml.rerankers import Reranker, build_reranker
from app.schemas.domain import ContextDocument, Evidence, PostContext


@dataclass(frozen=True)
class RetrievalSettings:
    search_limit_per_provider: int = 5
    max_queries: int = 4
    retrieve_limit: int = 30
    evidence_limit: int = 6
    include_thread_context: bool = True
    include_linked_pages: bool = True
    include_search: bool = True
    include_bluesky_search: bool = True
    include_web_search: bool = True
    linked_page_limit: int = 5
    chunking: vs.ChunkingConfig = vs.DEFAULT_CHUNKING_CONFIG


class RetrievalService:
    def __init__(
        self,
        *,
        rag_service: vs.RagService,
        search_providers: Sequence[sc.SearchProvider] = (),
        linked_page_fetcher: LinkedPageFetcher | None = None,
        settings: RetrievalSettings | None = None,
        scanner: PromptInjectionScanner | None = None,
        startup_warnings: Sequence[str] = (),
    ) -> None:
        provider_items, provider_warnings = bounded_items(
            search_providers, 50, "search_providers_iter_failed"
        )
        self._rag_service = rag_service
        self._search_providers = [cast(sc.SearchProvider, provider) for provider in provider_items]
        self._linked_page_fetcher = linked_page_fetcher or LinkedPageFetcher()
        self._settings = settings or RetrievalSettings()
        self._scanner = scanner or PromptInjectionScanner()
        self._startup_warnings = tuple([*warning_strings(startup_warnings), *provider_warnings])

    async def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] | None = None,
        settings: RetrievalSettings | None = None,
    ) -> d.RetrievalResult:
        opts = settings or self._settings
        search_queries, query_warnings = d.generate_search_queries_with_warnings(
            post, supplied_queries=queries, max_queries=opts.max_queries
        )
        documents, warnings, blocks = await self._collect_documents(post, search_queries, opts)
        warnings = [*query_warnings, *warnings]
        documents, url_warnings, url_blocks = self._filter_safe_document_urls(documents)
        warnings.extend(url_warnings)
        blocks.extend(url_blocks)
        safe_documents, prompt_flags = self._sanitize(documents)
        if not safe_documents:
            warnings.append("retrieval_no_documents")
            return d.make_retrieval_result(
                documents=[],
                evidence=[],
                queries=search_queries,
                prompt_flags=prompt_flags,
                warnings=warnings,
                private_url_blocks=blocks,
            )
        evidence, extra_flags = self._retrieve_evidence(search_queries, safe_documents, warnings)
        rag_diagnostics, diagnostic_warnings = safe_last_diagnostics(self._rag_service)
        warnings.extend(diagnostic_warnings)
        prompt_flags = d.dedupe_values([*prompt_flags, *rag_diagnostics.prompt_injection_flags])
        return d.make_retrieval_result(
            documents=safe_documents,
            evidence=evidence,
            queries=search_queries,
            prompt_flags=prompt_flags,
            warnings=[*warnings, *rag_diagnostics.warnings],
            private_url_blocks=blocks,
            extra_guardrail_flags=extra_flags,
        )

    async def _collect_documents(
        self,
        post: PostContext,
        queries: Sequence[str],
        settings: RetrievalSettings,
    ) -> tuple[list[ContextDocument], list[str], list[str]]:
        post_warnings = ba(post, "warnings", "post_warnings_field_failed")
        warnings = [*warning_strings(self._startup_warnings), *warning_strings(post_warnings)]
        documents, context_warnings = (
            d.documents_from_post_context_with_warnings(post)
            if settings.include_thread_context
            else ([], [])
        )
        warnings.extend(context_warnings)
        blocks = d.private_blocks_from_warnings(warnings)
        if settings.include_linked_pages:
            linked_documents, link_warnings, link_blocks = await self._linked_page_documents(
                ba(post, "links", "post_links_field_failed"),
                limit=settings.linked_page_limit,
            )
            documents.extend(linked_documents)
            warnings.extend(link_warnings)
            blocks.extend(link_blocks)
        providers = self._enabled_search_providers(settings)
        if settings.include_search and providers:
            search_documents, search_warnings = await self._search_documents(
                queries,
                providers,
                limit_per_provider=settings.search_limit_per_provider,
            )
            documents.extend(search_documents)
            warnings.extend(search_warnings)
            blocks.extend(d.private_blocks_from_warnings(search_warnings))
        return documents, warnings, blocks

    def _sanitize(
        self, documents: Sequence[ContextDocument]
    ) -> tuple[list[ContextDocument], list[str]]:
        sanitized, scans = sanitize_context_documents(
            d.dedupe_documents(documents),
            scanner=self._scanner,
        )
        sanitized = unique_documents_by_id(sanitized)
        flags = d.dedupe_values(flag for scan in scans for flag in scan.flags)
        return sanitized, flags

    def _retrieve_evidence(
        self,
        queries: Sequence[str],
        documents: list[ContextDocument],
        warnings: list[str],
    ) -> tuple[list[Evidence], list[str]]:
        try:
            return self._rag_service.retrieve("\n".join(queries), documents), []
        except Exception as exc:
            warnings.append(f"retrieval_failed:{exc.__class__.__name__}")
            return [], ["retrieval_unavailable"]

    async def _linked_page_documents(
        self,
        links: object,
        *,
        limit: int,
    ) -> tuple[list[ContextDocument], list[str], list[str]]:
        documents: list[ContextDocument] = []
        warnings: list[str] = []
        private_url_blocks: list[str] = []
        link_limit = safe_limit(limit)
        unique_links, overflow_count, link_iter_warnings = d.dedupe_limited_values_with_warnings(
            links, link_limit, "linked_page_iter_failed"
        )
        warnings.extend(link_iter_warnings)
        if overflow_count:
            warnings.append(f"linked_page_limit_exceeded:{overflow_count}")
        for index, url in enumerate(unique_links[:link_limit], start=1):
            result = await self._linked_page_fetcher.fetch(
                url,
                source_id=f"LINK-{text_hash(boundary_text(url, 'link_url_text_failed'))[:12]}",
            )
            warnings.extend(result.warnings)
            if result.blocked:
                block = (
                    f"blocked_link:{redact_url_for_warning(url)}:"
                    f"{'|'.join(result.warnings)}"
                )
                private_url_blocks.append(block)
                warnings.append(block)
            if result.document is None:
                continue
            metadata = {
                **result.document.metadata,
                "post_link_rank": index,
                "linked_from_post": True,
            }
            documents.append(result.document.model_copy(update={"metadata": metadata}))
        return documents, warnings, private_url_blocks

    async def _search_documents(
        self,
        queries: Sequence[str],
        providers: list[sc.SearchProvider],
        *,
        limit_per_provider: int,
    ) -> tuple[list[ContextDocument], list[str]]:
        documents: list[ContextDocument] = []
        warnings: list[str] = []
        for query in queries:
            bundle = await sc.collect_search_context(
                query,
                providers,
                limit_per_provider=limit_per_provider,
            )
            documents.extend(bundle.documents)
            warnings.extend(bundle.warnings)
        return documents, warnings

    def _filter_safe_document_urls(
        self,
        documents: Sequence[ContextDocument],
    ) -> tuple[list[ContextDocument], list[str], list[str]]:
        safe_documents: list[ContextDocument] = []
        warnings: list[str] = []
        blocks: list[str] = []
        for document in documents:
            source_type_attr = ba(document, "source_type", "source_type_field_failed")
            source_type = boundary_text(source_type_attr, "source_type_text_failed")
            allow_at_uri = source_type in {"bluesky", "thread"}
            document_url = ba(document, "url", "document_url_field_failed")
            safety = validate_source_url_metadata(
                document_url,
                allow_at_uri=allow_at_uri,
                resolver=self._linked_page_fetcher.resolver,
            )
            if safety.allowed:
                safe_documents.append(document)
                continue
            block = (
                f"blocked_document_url:"
                f"{safe_identifier(ba(document, 'id', 'document_id_field_failed'), prefix='DOC')}:"
                f"{redact_url_for_warning(document_url)}:{'|'.join(safety.warnings)}"
            )
            blocks.append(block)
            warnings.extend([*safety.warnings, block])
        return safe_documents, warnings, blocks

    def _enabled_search_providers(self, settings: RetrievalSettings) -> list[sc.SearchProvider]:
        if not (settings.include_bluesky_search or settings.include_web_search):
            return []
        return [
            provider
            for provider in self._search_providers
            if (
                settings.include_bluesky_search
                or not isinstance(provider, sc.BlueskySearchProvider)
            )
            and (
                settings.include_web_search
                or not isinstance(provider, sc.WebSearchProvider)
            )
        ]

def build_retrieval_service(
    *,
    settings: Settings | None = None,
    retrieval_settings: RetrievalSettings | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    vector_store: vs.VectorStore | None = None,
    reranker: Reranker[vs.DocumentChunk] | None = None,
    search_providers: Sequence[sc.SearchProvider] | None = None,
    linked_page_fetcher: LinkedPageFetcher | None = None,
) -> RetrievalService:
    app_settings = settings or get_settings()
    active_retrieval_settings = retrieval_settings or RetrievalSettings()
    fetcher = linked_page_fetcher or LinkedPageFetcher()
    vector_store, startup_warnings = _vector_store_or_fallback(app_settings, vector_store)
    embedding_provider = embedding_provider or OpenAIEmbeddingProvider(settings=app_settings)
    reranker = reranker or build_reranker(enable_hf=app_settings.enable_hf_reranker)
    if search_providers is None:
        search_providers = _default_search_providers(active_retrieval_settings, fetcher)
    rag_service = vs.RagService(
        embedding_provider=embedding_provider,
        vector_store=vector_store,
        reranker=reranker,
        chunking=active_retrieval_settings.chunking,
        retrieve_limit=active_retrieval_settings.retrieve_limit,
        evidence_limit=active_retrieval_settings.evidence_limit,
    )
    return RetrievalService(
        rag_service=rag_service,
        search_providers=search_providers,
        linked_page_fetcher=fetcher,
        settings=active_retrieval_settings,
        startup_warnings=startup_warnings,
    )


def _vector_store_or_fallback(
    settings: Settings,
    vector_store: vs.VectorStore | None,
) -> tuple[vs.VectorStore, list[str]]:
    if vector_store is not None:
        return vector_store, []
    try:
        return vs.QdrantVectorStore(path=settings.qdrant_path), []
    except Exception as exc:
        warning = f"qdrant_unavailable_using_in_memory_vector_store:{exc.__class__.__name__}"
        return vs.InMemoryVectorStore(), [warning]


def _default_search_providers(
    settings: RetrievalSettings,
    fetcher: LinkedPageFetcher,
) -> list[sc.SearchProvider]:
    providers: list[sc.SearchProvider] = []
    if settings.include_bluesky_search:
        providers.append(sc.BlueskySearchProvider(BlueskyClient(), fetcher.resolver))
    if settings.include_web_search:
        providers.append(sc.WebSearchProvider(fetcher=fetcher))
    return providers
