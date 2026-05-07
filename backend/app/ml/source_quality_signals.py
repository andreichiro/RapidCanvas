"""Source-quality signal extraction helpers."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite
from typing import Any

from app.ml import source_quality_rules as rules
from app.ml.boundary import boundary_attr, boundary_text
from app.schemas.domain import ContextDocument, PostContext

_metadata = rules.metadata
_metadata_text = rules.metadata_text
_domain = rules.domain
_author_domain = rules.author_domain
_tokens = rules.tokens
_safe_text = rules.safe_text
_safe_texts = rules.safe_texts
_bool = rules.bool_value
_safe_int = rules.safe_int
_parse_datetime = rules.parse_datetime


@dataclass(frozen=True)
class SourceQualitySignal:
    name: str
    weight: float
    reason: str


def build_quality_signals(
    post: PostContext,
    query: str,
    document: ContextDocument,
) -> list[SourceQualitySignal]:
    signals: list[SourceQualitySignal] = []
    _add(signals, "channel_prior", _channel_prior(document), "source channel prior")
    _role_signals(signals, document)
    _authority_signals(signals, post, document)
    _lexical_overlap_signal(signals, post, query, document)
    _sparse_target_penalty(signals, post, document)
    _named_entity_penalty(signals, post, query, document)
    _freshness_signals(signals, post, query, document)
    _quality_penalties(signals, document)
    _commercial_penalties(signals, document)
    _prompt_injection_penalty(signals, document)
    return signals


def has_disqualifying_reason(reasons: Sequence[str], score: float) -> bool:
    reason_text = " ".join(reasons).lower()
    disqualifying_markers = (
        "prompt_injection", "fetch_status_5", "commercial_catalog", "seo_or_scraper",
        "robots_disallowed", "empty_image_evidence", "off_topic_named_entities",
        "sparse_target_web_search",
    )
    if any(marker in reason_text for marker in disqualifying_markers):
        return True
    return "off_topic_low_lexical_overlap" in reason_text and score < 0.7


def citation_threshold(document: ContextDocument) -> float | None:
    metadata = _metadata(document)
    if document.source_type == "image" and _empty_image_evidence(document):
        return None
    thresholds: list[tuple[bool, float]] = [
        (document.source_type == "thread", 0.25),
        (document.source_type == "image", 0.3),
        (_bool(metadata.get("linked_from_post")), 0.4),
        (_bool(metadata.get("snippet_only")), 0.7),
        (document.source_type in {"web", "bluesky"}, 0.55),
    ]
    for matched, threshold in thresholds:
        if matched:
            return threshold
    return None


def citation_role(document: ContextDocument, eligible: bool) -> str:
    if not eligible:
        return "diagnostic"
    if _bool(_metadata(document).get("snippet_only")):
        return "secondary"
    return "primary"


def source_channel_prior(document: ContextDocument) -> float:
    priors = {"thread": 0.92, "image": 0.72, "bluesky": 0.66, "web": 0.5}
    return priors.get(document.source_type, 0.4)


def _channel_prior(document: ContextDocument) -> float:
    metadata = _metadata(document)
    if document.source_type == "thread":
        return 0.62
    if document.source_type == "image":
        return 0.52
    if document.source_type == "bluesky":
        return 0.42
    if _bool(metadata.get("linked_from_post")):
        return 0.48
    return 0.32


def _role_signals(signals: list[SourceQualitySignal], document: ContextDocument) -> None:
    metadata = _metadata(document)
    role = boundary_text(
        metadata.get("image_evidence_role") or metadata.get("role", ""),
        "source_role_text_failed",
    ).lower()
    if role in {"target_post", "post", "visible_post"} or document.id == "POST-target":
        _add(signals, "target_post", 0.24, "target_post_context")
    if "parent" in role:
        _add(signals, "parent_thread", 0.18, "parent_thread_context")
    if "quote" in role or "quoted" in role:
        _add(signals, "quote_context", 0.18, "quote_context")
    if document.source_type == "image":
        _add(signals, "image_evidence", 0.14, "image_evidence")
    if _bool(metadata.get("linked_from_post")):
        _add(signals, "direct_post_link", 0.24, "direct_post_link")


def _authority_signals(
    signals: list[SourceQualitySignal],
    post: PostContext,
    document: ContextDocument,
) -> None:
    domain = _domain(document.url) or _metadata_text(document, "domain")
    author_domain = _author_domain(post.author)
    for name, weight, reason in _authority_boosts(domain, author_domain, document):
        _add(signals, name, weight, reason)


def _authority_boosts(
    domain: str,
    author_domain: str,
    document: ContextDocument,
) -> list[tuple[str, float, str]]:
    boosts: list[tuple[str, float, str]] = []
    if _matches_author_domain(domain, author_domain):
        boosts.append(("author_domain", 0.28, "author_domain_match"))
    if domain in rules.OFFICIAL_DOMAINS or domain.endswith((".gov", ".edu")):
        boosts.append(("official_domain", 0.18, "official_or_primary_domain"))
    if domain.endswith(".github.io") or domain == "github.com":
        boosts.append(("github_source", 0.12, "github_source_page"))
    if domain in rules.NEWS_DOMAINS:
        boosts.append(("news_domain", 0.12, "recognized_news_domain"))
    if _bool(_metadata(document).get("primary_source")):
        boosts.append(("primary_source", 0.18, "primary_source_metadata"))
    return boosts


def _matches_author_domain(domain: str, author_domain: str) -> bool:
    return bool(domain and author_domain) and (
        domain == author_domain or domain.endswith(f".{author_domain}")
    )


def _lexical_overlap_signal(
    signals: list[SourceQualitySignal],
    post: PostContext,
    query: str,
    document: ContextDocument,
) -> None:
    source_tokens = _tokens(_source_text(post, query, include_author=True))
    doc_tokens = _tokens(f"{document.title} {document.text}")
    if not source_tokens or not doc_tokens:
        _add(signals, "low_lexical_overlap", -0.12, "off_topic_low_lexical_overlap")
        return
    overlap = len(source_tokens & doc_tokens) / max(1, len(source_tokens))
    if overlap >= 0.45:
        _add(signals, "high_lexical_overlap", 0.3, "high_lexical_overlap")
    elif overlap >= 0.25:
        _add(signals, "medium_lexical_overlap", 0.16, "medium_lexical_overlap")
    elif overlap >= 0.12:
        _add(signals, "low_positive_overlap", 0.06, "some_lexical_overlap")
    else:
        _add(signals, "off_topic", -0.18, "off_topic_low_lexical_overlap")


def _named_entity_penalty(
    signals: list[SourceQualitySignal],
    post: PostContext,
    query: str,
    document: ContextDocument,
) -> None:
    source_text = _source_text(post, query)
    source_entities = rules.entity_tokens(source_text)
    document_entities = rules.entity_tokens(f"{document.title} {document.text}")
    if not source_entities or len(document_entities - source_entities) < 5:
        return
    source_tokens = _tokens(source_text)
    document_tokens = _tokens(f"{document.title} {document.text}")
    overlap = len(source_tokens & document_tokens) / max(1, len(source_tokens))
    metadata = _metadata(document)
    authority_context = (
        _bool(metadata.get("linked_from_post"))
        or _bool(metadata.get("primary_source"))
        or bool(_domain(document.url) in rules.OFFICIAL_DOMAINS)
    )
    if overlap < 0.35 or not authority_context:
        _add(signals, "off_topic_entities", -0.1, "off_topic_named_entities")


def _sparse_target_penalty(
    signals: list[SourceQualitySignal],
    post: PostContext,
    document: ContextDocument,
) -> None:
    metadata = _metadata(document)
    if document.source_type != "web" or _bool(metadata.get("linked_from_post")):
        return
    post_tokens = _tokens(_safe_text(boundary_attr(post, "text", "post_text_field_failed")))
    if len(post_tokens) <= 2:
        _add(signals, "sparse_target_web", -0.36, "sparse_target_web_search")


def _source_text(post: PostContext, query: str, *, include_author: bool = False) -> str:
    parts = [
        _safe_text(boundary_attr(post, "text", "post_text_field_failed")),
        query,
        *_safe_texts(boundary_attr(post, "parent_texts", "post_parent_texts_field_failed")),
        *_safe_texts(boundary_attr(post, "quoted_texts", "post_quoted_texts_field_failed")),
        *_image_texts(post),
    ]
    if include_author:
        parts.append(_safe_text(boundary_attr(post, "author", "post_author_field_failed")))
    return " ".join(parts)


def _image_texts(post: PostContext) -> list[str]:
    images = boundary_attr(post, "images", "post_images_field_failed")
    if not isinstance(images, Sequence) or isinstance(images, str | bytes | bytearray):
        return []
    return [
        text
        for image in images[:10]
        if (text := _safe_text(boundary_attr(image, "alt_text", "")))
    ]


def _freshness_signals(
    signals: list[SourceQualitySignal],
    post: PostContext,
    query: str,
    document: ContextDocument,
) -> None:
    query_text = _source_text(post, query).lower()
    if not any(marker in query_text for marker in rules.CURRENT_EVENT_MARKERS):
        return
    metadata = _metadata(document)
    published = _parse_datetime(metadata.get("published_at") or metadata.get("date"))
    post_created_at = _parse_datetime(boundary_attr(post, "created_at", "post_created_at_failed"))
    if published is None:
        if document.source_type == "web" and not _bool(metadata.get("linked_from_post")):
            _add(signals, "missing_current_date", -0.08, "current_event_missing_date_signal")
        return
    if post_created_at is None:
        return
    age_days = abs((post_created_at - published).days)
    if age_days <= 14:
        _add(signals, "fresh_current_source", 0.12, "fresh_current_event_date")
    elif age_days > 365:
        _add(signals, "stale_current_source", -0.2, "stale_current_event_source")


def _quality_penalties(signals: list[SourceQualitySignal], document: ContextDocument) -> None:
    metadata = _metadata(document)
    snippet_only = _bool(metadata.get("snippet_only"))
    if document.source_type == "image" and _empty_image_evidence(document):
        _add(signals, "empty_image_evidence", -0.5, "empty_image_evidence")
    _snippet_penalties(signals, document, snippet_only)
    _fetch_penalties(signals, metadata)
    extracted_length = _safe_int(metadata.get("extracted_length")) or len(document.text.strip())
    if not snippet_only:
        _length_penalty(signals, document, extracted_length)
        _rank_penalty(signals, metadata)


def _snippet_penalties(
    signals: list[SourceQualitySignal],
    document: ContextDocument,
    snippet_only: bool,
) -> None:
    if snippet_only:
        _add(signals, "snippet_only", -0.08, "snippet_only_fallback")
        if len(_tokens(document.text)) < 8:
            _add(signals, "thin_snippet", -0.25, "thin_snippet_only_fallback")


def _fetch_penalties(signals: list[SourceQualitySignal], metadata: dict[str, Any]) -> None:
    if _robots_disallowed(metadata):
        _add(signals, "robots_disallowed", -0.36, "robots_disallowed_fetch")
    if metadata.get("fetch_success") is False:
        _add(signals, "fetch_failed", -0.2, "fetch_failed")
    status = _safe_int(metadata.get("fetch_status") or metadata.get("status"))
    if status is not None and status >= 400:
        _add(signals, "fetch_bad_status", -0.2, f"fetch_status_{status}")


def _robots_disallowed(metadata: dict[str, Any]) -> bool:
    if _bool(metadata.get("robots_disallowed")):
        return True
    warnings = metadata.get("fetch_warnings") or metadata.get("warnings") or []
    if isinstance(warnings, str):
        return "robots_disallowed" in warnings.lower()
    return isinstance(warnings, Sequence) and any(
        "robots_disallowed" in boundary_text(warning).lower() for warning in warnings
    )


def _empty_image_evidence(document: ContextDocument) -> bool:
    return document.text.strip().lower() in {
        "",
        "image was present but had no alt text.",
        "image was present but had no alt text",
        "vision unavailable",
        "no image description available",
        "no image description available.",
    }


def _length_penalty(
    signals: list[SourceQualitySignal],
    document: ContextDocument,
    extracted_length: int,
) -> None:
    if document.source_type != "web":
        return
    if extracted_length < 40:
        _add(signals, "empty_or_tiny_text", -0.24, "low_extracted_text_length")
    elif extracted_length < 160:
        _add(signals, "short_text", -0.1, "low_extracted_text_length")


def _rank_penalty(signals: list[SourceQualitySignal], metadata: dict[str, Any]) -> None:
    rank = _safe_int(metadata.get("rank") or metadata.get("search_rank"))
    if rank is not None and rank > 15:
        _add(signals, "rank_drift", -0.16, "search_rank_drift")
    elif rank is not None and rank > 8:
        _add(signals, "rank_drift", -0.08, "search_rank_drift")


def _commercial_penalties(signals: list[SourceQualitySignal], document: ContextDocument) -> None:
    domain = _domain(document.url)
    text = f"{document.title} {document.text} {document.url}".lower()
    if domain and any(marker in domain for marker in rules.COMMERCIAL_DOMAIN_MARKERS):
        _add(signals, "commercial_catalog", -0.42, "commercial_catalog_domain")
    if any(marker in text for marker in rules.COMMERCIAL_TEXT_MARKERS):
        _add(signals, "commercial_catalog", -0.28, "commercial_catalog_content")
    if any(marker in text for marker in rules.SEO_MARKERS):
        _add(signals, "seo_or_scraper", -0.24, "seo_or_scraper_content")


def _prompt_injection_penalty(
    signals: list[SourceQualitySignal],
    document: ContextDocument,
) -> None:
    metadata = _metadata(document)
    flags = metadata.get("prompt_injection_flags") or metadata.get("guardrail_flags") or []
    flags = [flags] if isinstance(flags, str) else flags
    text = f"{document.title} {document.text}".lower()
    has_text = any(marker in text for marker in _PROMPT_INJECTION_TEXT_MARKERS)
    if flags or has_text:
        _add(signals, "prompt_injection", -0.72, "prompt_injection_risk")


_PROMPT_INJECTION_TEXT_MARKERS = (
    "ignore previous instructions", "developer prompt", "system prompt",
    "reveal the prompt", "disable citations",
)


def _add(signals: list[SourceQualitySignal], name: str, weight: float, reason: str) -> None:
    if isfinite(weight) and weight:
        signals.append(SourceQualitySignal(name=name, weight=weight, reason=reason))
