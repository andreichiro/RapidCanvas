"""Retrieval diagnostics surfaced for agent trace and guardrails."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TypeVar, cast

from app.guardrails.prompt_injection import PromptInjectionScanResult
from app.ml.boundary import boundary_text, bounded_items, safe_limit
from app.ml.c2_policy import diagnostic_strings, diagnostic_text, safe_evidence_for_documents
from app.schemas.domain import ContextDocument, Evidence, PostContext

T = TypeVar("T")
_WORD_RE = re.compile(r"[A-Za-z0-9_@#:.+-]+")
_BLOCK_WARNING_PREFIXES = ("blocked_url:", "blocked_link:", "blocked_document_url:")
DocumentWarningResult = tuple[list[ContextDocument], list[str]]


@dataclass(frozen=True)
class RetrievalDiagnostics:
    prompt_injection_flags: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    evidence_scores: dict[str, float] = field(default_factory=dict)
    reranker_scores: dict[str, float] = field(default_factory=dict)
    private_url_blocks: tuple[str, ...] = ()
    search_queries: tuple[str, ...] = ()
    document_count: int = 0
    evidence_count: int = 0
    source_quality: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class RetrievalResult:
    documents: list[ContextDocument]
    evidence: list[Evidence]
    diagnostics: RetrievalDiagnostics
    warnings: list[str] = field(default_factory=list)
    guardrail_flags: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)
    private_url_blocks: list[str] = field(default_factory=list)


def retrieval_diagnostics(
    documents: list[ContextDocument],
    scans: Sequence[PromptInjectionScanResult],
) -> RetrievalDiagnostics:
    flags: list[str] = []
    warnings: list[str] = []
    for document, scan in zip(documents, scans, strict=True):
        for flag in scan.flags:
            flags.append(flag)
            warnings.append(f"prompt_injection_risk:{document.id}:{flag}")
    return RetrievalDiagnostics(
        prompt_injection_flags=tuple(dict.fromkeys(flags)),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def make_retrieval_result(
    *,
    documents: list[ContextDocument],
    evidence: list[Evidence],
    queries: list[str],
    prompt_flags: Sequence[object],
    warnings: Sequence[object],
    private_url_blocks: Sequence[object],
    extra_guardrail_flags: Sequence[object] = (),
    reranker_scores: Mapping[str, float] | None = None,
    source_quality: Sequence[Mapping[str, object]] = (),
) -> RetrievalResult:
    safe_evidence_result = safe_evidence_for_documents(evidence, documents)
    safe_evidence = safe_evidence_result.evidence
    prompt_flag_values = dedupe_values(
        [*diagnostic_strings(prompt_flags), *safe_evidence_result.prompt_flags])
    warning_values = dedupe_values(
        [*diagnostic_strings(warnings), *safe_evidence_result.warnings])
    source_ids = dedupe_values(item.source_id for item in safe_evidence)
    scores = {item.id: item.score for item in safe_evidence}
    private_blocks = dedupe_values(diagnostic_strings(private_url_blocks))
    query_values = dedupe_values(diagnostic_strings(queries))
    extra_flags = diagnostic_strings(extra_guardrail_flags)
    guardrail_flags = dedupe_values(
        [
            *(["prompt_injection_risk"] if prompt_flag_values else []),
            *prompt_flag_values,
            *(["private_url_blocked"] if private_blocks else []),
            *extra_flags,
        ]
    )
    diagnostics = RetrievalDiagnostics(
        prompt_injection_flags=tuple(prompt_flag_values),
        warnings=tuple(warning_values),
        source_ids=tuple(source_ids),
        evidence_scores=scores,
        reranker_scores=dict(reranker_scores or {}),
        private_url_blocks=tuple(private_blocks),
        search_queries=tuple(query_values),
        document_count=len(documents),
        evidence_count=len(safe_evidence),
        source_quality=tuple(dict(item) for item in source_quality),
    )
    return RetrievalResult(
        documents=documents,
        evidence=safe_evidence,
        diagnostics=diagnostics,
        warnings=list(diagnostics.warnings),
        guardrail_flags=guardrail_flags,
        source_ids=source_ids,
        scores=scores,
        queries=query_values,
        private_url_blocks=list(diagnostics.private_url_blocks),
    )


def documents_from_post_context_with_warnings(post: PostContext) -> DocumentWarningResult:
    post_url = _context_text(_context_field(post, "url")) or "about:blank"
    post_at_uri = _context_text(_context_field(post, "at_uri"))
    documents = [_target_document(post)]
    parent_texts, parent_warnings = _context_texts_with_warnings(
        _context_field(post, "parent_texts", []), "post_parent_texts_iter_failed"
    )
    quote_texts, quote_warnings = _context_texts_with_warnings(
        _context_field(post, "quoted_texts", []), "post_quoted_texts_iter_failed"
    )
    images, image_warnings = _context_items_with_warnings(
        _context_field(post, "images", []), "post_images_iter_failed"
    )
    warnings = [*parent_warnings, *quote_warnings, *image_warnings]
    documents.extend(
        ContextDocument(
            id=f"POST-parent-{index}",
            source_type="thread",
            title="Bluesky parent context",
            url=post_url,
            text=text,
            metadata={"role": "parent_post", "parent_index": index, "at_uri": post_at_uri},
        )
        for index, text in enumerate(parent_texts, start=1)
    )
    documents.extend(
        ContextDocument(
            id=f"POST-quote-{index}",
            source_type="thread",
            title="Bluesky quoted context",
            url=post_url,
            text=text,
            metadata={"role": "quoted_post", "quote_index": index, "at_uri": post_at_uri},
        )
        for index, text in enumerate(quote_texts, start=1)
    )
    documents.extend(
        ContextDocument(
            id=f"POST-image-{index}",
            source_type="image",
            title="Bluesky image alt text",
            url=_context_text(_context_field(image, "url")) or "about:blank",
            text=_context_text(_context_field(image, "alt_text"))
            or "Image was present but had no alt text.",
            metadata={"role": "image_alt_text", "image_index": index, "at_uri": post_at_uri},
        )
        for index, image in enumerate(images, start=1)
    )
    return documents, warnings


def generate_search_queries(
    post: PostContext,
    *,
    supplied_queries: Sequence[str] | None = None,
    max_queries: int = 4,
) -> list[str]:
    return generate_search_queries_with_warnings(
        post, supplied_queries=supplied_queries, max_queries=max_queries
    )[0]


def generate_search_queries_with_warnings(
    post: PostContext,
    *,
    supplied_queries: Sequence[str] | None = None,
    max_queries: int = 4,
) -> tuple[list[str], list[str]]:
    max_queries = safe_limit(max_queries)
    if supplied_queries is not None:
        texts, warnings = _context_texts_with_warnings(
            supplied_queries, "supplied_queries_iter_failed"
        )
        cleaned = (_clean_query(query) for query in texts)
        return dedupe_values(query for query in cleaned if query)[:max_queries], warnings

    text_query = _snippet_query(_context_text(_context_field(post, "text")))
    quoted_texts, quote_warnings = _context_texts_with_warnings(
        _context_field(post, "quoted_texts", []), "post_quoted_texts_iter_failed"
    )
    parent_texts, parent_warnings = _context_texts_with_warnings(
        _context_field(post, "parent_texts", []), "post_parent_texts_iter_failed"
    )
    candidates = [
        text_query,
        f"{_context_text(_context_field(post, 'author'))} {text_query}".strip(),
        *(_snippet_query(text) for text in quoted_texts),
        *(_snippet_query(text) for text in parent_texts),
    ]
    cleaned = (_clean_query(query) for query in candidates)
    queries = dedupe_values(query for query in cleaned if query)
    fallback = (
        _context_text(_context_field(post, "author"))
        or _context_text(_context_field(post, "at_uri"))
        or _context_text(_context_field(post, "url"))
    )
    return (queries or [fallback])[:max_queries], [*quote_warnings, *parent_warnings]


def dedupe_values(values: Iterable[T]) -> list[T]:
    if isinstance(values, str | bytes | bytearray | Mapping):
        values = [cast(T, values)]
    seen: set[str] = set()
    deduped: list[T] = []
    for value in values:
        if not value:
            continue
        key = boundary_text(value, "dedupe_key_failed")
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def vector_store_backend_name(vector_store: object) -> str:
    name = getattr(vector_store, "backend_name", None)
    if isinstance(name, str) and name:
        return name
    return f"vector_store:{type(vector_store).__name__}"


def diagnostic_warnings(warnings: Sequence[str], vector_store_backend: str) -> list[str]:
    suffix = [vector_store_backend] if vector_store_backend else []
    return list(dict.fromkeys([*warnings, *suffix]))


def dedupe_limited_values_with_warnings(
    values: object,
    limit: int,
    failure_prefix: str,
) -> tuple[list[object], int | None, list[str]]:
    value_limit = safe_limit(limit)
    if isinstance(values, str | bytes | bytearray | Mapping):
        limited_scalar = cast(list[object], list(dedupe_values([values]))[:value_limit])
        return limited_scalar, 0 if value_limit else 1, []
    if not isinstance(values, Iterable):
        return list(dedupe_values([values]))[:value_limit], 0 if value_limit else 1, []
    items, warnings = bounded_items(values, value_limit, failure_prefix)
    overflow_count = None
    if isinstance(values, Sequence) and not warnings:
        try:
            overflow_count = max(0, len(values) - value_limit)
        except Exception as exc:
            warnings.append(f"{failure_prefix}:{exc.__class__.__name__}")
    return dedupe_values(items), overflow_count, warnings


def dedupe_documents(documents: Sequence[ContextDocument]) -> list[ContextDocument]:
    by_id: dict[str, ContextDocument] = {}
    for document in documents:
        document_id = boundary_text(_context_field(document, "id"), "document_id_text_failed")
        if document_id not in by_id:
            by_id[document_id] = document
    return list(by_id.values())


def private_blocks_from_warnings(warnings: Sequence[object]) -> list[str]:
    return [
        text for warning in warnings
        if (text := diagnostic_text(warning)).startswith(_BLOCK_WARNING_PREFIXES)
    ]


def _target_document(post: PostContext) -> ContextDocument:
    return ContextDocument(
        id="POST-target",
        source_type="thread",
        title=f"Bluesky post by {_context_text(_context_field(post, 'author'))}",
        url=_context_text(_context_field(post, "url")) or "about:blank",
        text=_context_text(_context_field(post, "text")) or "The fetched post has no text.",
        metadata={
            "role": "target_post",
            "author": _context_text(_context_field(post, "author")),
            "at_uri": _context_text(_context_field(post, "at_uri")),
            "created_at": _created_at_text(_context_field(post, "created_at")),
        },
    )


def _context_texts_with_warnings(value: object, failure_prefix: str) -> tuple[list[str], list[str]]:
    items, warnings = _context_items_with_warnings(value, failure_prefix)
    return [text for item in items if (text := _context_text(item)).strip()], warnings


def _context_items_with_warnings(value: object, failure_prefix: str) -> tuple[list[object], list[str]]:  # noqa: E501
    return ([], []) if value is None else bounded_items(value, 50, failure_prefix)


def _context_field(value: object, key: str, default: object = "") -> object:
    try:
        if isinstance(value, Mapping):
            return value.get(key, default)
        return getattr(value, key)
    except Exception as exc:
        return default if default != "" else f"context_field_failed:{exc.__class__.__name__}"


def _context_text(value: object) -> str:
    return boundary_text(value, "context_text_failed")


def _created_at_text(value: object) -> str:
    try:
        isoformat = getattr(value, "isoformat", None)
        return _context_text(isoformat()) if callable(isoformat) else _context_text(value)
    except Exception as exc:
        return f"context_text_failed:{exc.__class__.__name__}"


def _snippet_query(text: str, max_terms: int = 12) -> str:
    return " ".join(_WORD_RE.findall(text)[:max_terms])


def _clean_query(query: str) -> str:
    return " ".join(query.split())[:240]
