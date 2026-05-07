from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any, cast

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
from app.ml import image as img
from app.ml import retrieval_backfill
from app.ml import retrieval_collectors as rc
from app.ml import source_quality as sq
from app.ml.boundary import boundary_attr as ba
from app.ml.boundary import boundary_text, bounded_items
from app.ml.c2_policy import unique_documents_by_id
from app.ml.embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
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
    linked_page_concurrency: int = 4
    search_concurrency: int = 4
    retrieval_timeout_seconds: float = 25.0
    chunking: vs.ChunkingConfig = vs.DEFAULT_CHUNKING_CONFIG


class RetrievalService:
    def __init__(
        self,
        *,
        rag_service: vs.RagService,
        search_providers: Sequence[sc.SearchProvider] = (),
        linked_page_fetcher: LinkedPageFetcher | None = None,
        settings: RetrievalSettings | None = None,
        app_settings: Settings | None = None,
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
        self._app_settings = app_settings or get_settings()
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
        documents, warnings, blocks = await self._collect_documents(
            post,
            search_queries,
            opts,
            deadline=rc.deadline(opts.retrieval_timeout_seconds),
        )
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
        query_text = "\n".join(search_queries)
        safe_documents, source_quality = sq.annotate_source_quality(
            post, query_text, safe_documents
        )
        safe_documents = sq.dedupe_equivalent_documents(safe_documents)
        evidence, extra_flags = self._retrieve_evidence(
            post,
            search_queries,
            safe_documents,
            warnings,
            evidence_limit=opts.evidence_limit,
        )
        rag_diagnostics, diagnostic_warnings = safe_last_diagnostics(self._rag_service)
        prompt_flags = d.dedupe_values([*prompt_flags, *rag_diagnostics.prompt_injection_flags])
        return d.make_retrieval_result(
            documents=safe_documents,
            evidence=evidence,
            queries=search_queries,
            prompt_flags=prompt_flags,
            warnings=[*warnings, *diagnostic_warnings, *rag_diagnostics.warnings],
            private_url_blocks=blocks,
            extra_guardrail_flags=extra_flags,
            reranker_scores=rag_diagnostics.reranker_scores,
            source_quality=source_quality,
        )

    async def _collect_documents(
        self,
        post: PostContext,
        queries: Sequence[str],
        settings: RetrievalSettings,
        *,
        deadline: float | None,
    ) -> tuple[list[ContextDocument], list[str], list[str]]:
        post_warnings = ba(post, "warnings", "post_warnings_field_failed")
        warnings = [*warning_strings(self._startup_warnings), *warning_strings(post_warnings)]
        documents, context_warnings = (
            d.documents_from_post_context_with_warnings(post)
            if settings.include_thread_context
            else ([], [])
        )
        warnings.extend(context_warnings)
        if settings.include_thread_context and self._app_settings.enable_image_understanding:
            documents = img.without_basic_image_alt_documents(documents)
            image_documents, image_warnings = self._image_context_documents(post)
            documents.extend(image_documents)
            warnings.extend(image_warnings)
        blocks = d.private_blocks_from_warnings(warnings)
        if settings.include_linked_pages:
            linked_documents, link_warnings, link_blocks = await rc.collect_linked_page_documents(
                ba(post, "links", "post_links_field_failed"),
                fetcher=self._linked_page_fetcher,
                limit=settings.linked_page_limit,
                concurrency=settings.linked_page_concurrency,
                timeout_seconds=rc.remaining_timeout(deadline),
            )
            documents.extend(linked_documents)
            warnings.extend(link_warnings)
            blocks.extend(link_blocks)
        providers = self._enabled_search_providers(settings)
        if settings.include_search and providers:
            search_documents, search_warnings = await rc.collect_search_documents(
                queries,
                providers,
                limit_per_provider=settings.search_limit_per_provider,
                concurrency=settings.search_concurrency,
                timeout_seconds=rc.remaining_timeout(deadline),
            )
            documents.extend(search_documents)
            warnings.extend(search_warnings)
            blocks.extend(d.private_blocks_from_warnings(search_warnings))
        return documents, warnings, blocks

    def _image_context_documents(
        self,
        post: PostContext,
    ) -> tuple[list[ContextDocument], list[str]]:
        images, image_iter_warnings = bounded_items(
            ba(post, "images", "post_images_field_failed"), 20, "image_iter_failed"
        )
        image_refs, coercion_warnings = img.coerce_image_refs(images)
        describe_image = (
            (
                lambda image: img.describe_image_with_openai(
                    image,
                    settings=self._app_settings,
                )
            )
            if self._app_settings.openai_api_key is not None
            else None
        )
        result = img.build_image_context_documents(
            image_refs,
            vision_enabled=True,
            describe_image=describe_image,
            vision_model=self._app_settings.vision_model,
        )
        return img.runtime_image_documents(result.documents), [
            *image_iter_warnings,
            *coercion_warnings,
            *result.warnings,
        ]

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
        post: PostContext,
        queries: Sequence[str],
        documents: list[ContextDocument],
        warnings: list[str],
        *,
        evidence_limit: int,
    ) -> tuple[list[Evidence], list[str]]:
        try:
            query_text = "\n".join(queries)
            namespace = vs.retrieval_namespace(
                query_text,
                documents,
                request_key=ba(post, "at_uri", "post_at_uri_field_failed"),
            )
            evidence = _call_rag_retrieve(
                self._rag_service, query_text, documents, namespace=namespace
            )
            quality_evidence = retrieval_backfill.with_quality_backfill(
                documents, evidence, limit=evidence_limit
            )
            return quality_evidence, []
        except Exception as exc:
            warnings.append(f"retrieval_failed:{exc.__class__.__name__}")
            return [], ["retrieval_unavailable"]

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
            and (settings.include_web_search or not isinstance(provider, sc.WebSearchProvider))
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
        app_settings=app_settings,
    )


def _vector_store_or_fallback(
    settings: Settings,
    vector_store: vs.VectorStore | None,
) -> tuple[vs.VectorStore, list[str]]:
    if vector_store is not None:
        return vector_store, []
    try:
        return vs.QdrantVectorStore(
            url=settings.qdrant_url,
            path=settings.qdrant_path,
            collection_scope=settings.embedding_model,
        ), []
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


def _call_rag_retrieve(
    rag_service: Any,
    query_text: str,
    documents: list[ContextDocument],
    *,
    namespace: str,
) -> list[Evidence]:
    retrieve = rag_service.retrieve
    if _accepts_namespace(retrieve):
        return cast(list[Evidence], retrieve(query_text, documents, namespace=namespace))
    return cast(list[Evidence], retrieve(query_text, documents))


def _accepts_namespace(callable_obj: Any) -> bool:
    try:
        params = signature(callable_obj).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        param.kind is Parameter.VAR_KEYWORD
        or (
            param.kind in {Parameter.KEYWORD_ONLY, Parameter.POSITIONAL_OR_KEYWORD}
            and param.name == "namespace"
        )
        for param in params
    )
