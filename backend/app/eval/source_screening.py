"""Eval-only source screening helpers for weak-answer detection."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

COMMERCIAL_DOMAIN_MARKERS = (
    "cardboardconnection",
    "cards.",
    "comc.",
    "ebay.",
    "etsy.",
    "marketplace.",
    "shop.",
    "tcdb.",
)
COMMERCIAL_TEXT_MARKERS = (
    "buy",
    "catalog",
    "checklist",
    "collectible",
    "coupon",
    "marketplace",
    "price guide",
    "shopping",
    "trading card",
)
SEO_MARKERS = (
    "affiliate",
    "best price",
    "click here",
    "coupon code",
    "sponsored",
    "top 10",
)


def commercial_or_scraper_source(source: Mapping[str, Any]) -> bool:
    """Return true for catalog/marketplace/SEO sources that should fail eval trust."""

    text = _normalize(_source_text(source))
    domain = _domain(str(source.get("url", "")))
    return any(marker in domain for marker in COMMERCIAL_DOMAIN_MARKERS) or any(
        _normalize(marker) in text for marker in (*COMMERCIAL_TEXT_MARKERS, *SEO_MARKERS)
    )


def citation_ineligible_source(source: Mapping[str, Any]) -> bool:
    """Return true when source metadata says it cannot safely support citations."""

    metadata = source.get("metadata")
    value = source.get("citation_eligible")
    if value is None and isinstance(metadata, Mapping):
        value = metadata.get("citation_eligible")
    return value is False or _risky_citation_metadata(source, metadata)


def _risky_citation_metadata(source: Mapping[str, Any], metadata: object) -> bool:
    return any(
        (
            _flagged_metadata_value(source, metadata, "prompt_injection_flags"),
            _flagged_metadata_value(source, metadata, "guardrail_flags"),
            _flagged_metadata_value(source, metadata, "source_safety_flags"),
            _contains_risk_text(source, metadata, "quality_reasons"),
            _contains_risk_text(source, metadata, "warnings"),
            _bool_value(source, metadata, "prompt_injection_risk"),
            _bool_value(source, metadata, "blocked"),
            _bool_value(source, metadata, "private_url_blocked"),
            _bool_value(source, metadata, "robots_disallowed"),
            _bool_value(source, metadata, "fetch_success") is False,
            _status_failed(source, metadata, "fetch_status"),
            _status_failed(source, metadata, "status"),
            _status_failed(source, metadata, "http_status"),
        )
    )


def _flagged_metadata_value(source: Mapping[str, Any], metadata: object, key: str) -> bool:
    value = _metadata_value(source, metadata, key)
    if isinstance(value, str):
        return _risk_text(value)
    if isinstance(value, list | tuple | set):
        return any(_risk_text(str(item)) for item in value)
    return bool(value)


def _contains_risk_text(source: Mapping[str, Any], metadata: object, key: str) -> bool:
    value = _metadata_value(source, metadata, key)
    if isinstance(value, str):
        return _risk_text(value)
    if isinstance(value, list | tuple | set):
        return any(_risk_text(str(item)) for item in value)
    return False


def _metadata_value(source: Mapping[str, Any], metadata: object, key: str) -> object:
    if key in source:
        return source.get(key)
    if isinstance(metadata, Mapping):
        return metadata.get(key)
    return None


def _bool_value(source: Mapping[str, Any], metadata: object, key: str) -> bool | None:
    value = _metadata_value(source, metadata, key)
    return value if isinstance(value, bool) else None


def _status_failed(source: Mapping[str, Any], metadata: object, key: str) -> bool:
    value = _metadata_value(source, metadata, key)
    if isinstance(value, int):
        return value >= 400
    if isinstance(value, str) and value.isdigit():
        return int(value) >= 400
    return isinstance(value, str) and _normalize(value) in {
        "failed",
        "error",
        "blocked",
        "disallowed",
    }


def _risk_text(value: str) -> bool:
    normalized = _normalize(value)
    risk_markers = (
        "prompt injection",
        "prompt injection risk",
        "ignore previous",
        "system prompt",
        "developer message",
        "private url blocked",
        "unsafe",
        "fetch failed",
        "failed fetch",
        "blocked",
    )
    return any(marker in normalized for marker in risk_markers)


def _source_text(source: Mapping[str, Any]) -> str:
    metadata = source.get("metadata")
    metadata_text = ""
    if isinstance(metadata, Mapping):
        metadata_text = " ".join(str(value) for value in metadata.values())
    return " ".join(
        str(value)
        for value in (
            source.get("title", ""),
            source.get("snippet", ""),
            source.get("url", ""),
            metadata_text,
        )
    )


def _domain(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
