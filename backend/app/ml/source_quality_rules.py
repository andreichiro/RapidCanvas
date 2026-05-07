"""Shared constants and coercion helpers for source quality scoring."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from app.ml.boundary import boundary_text, bounded_items
from app.schemas.domain import ContextDocument

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{1,}")
ENTITY_RE = re.compile(r"\b(?:[A-Z][A-Za-z0-9.+#-]{2,}|[A-Z]{2,}|[0-9]{4})\b")
OFFICIAL_DOMAINS = (
    "docs.python.org",
    "github.com",
    "ietf.org",
    "w3.org",
    "atproto.com",
    "bsky.social",
)
NEWS_DOMAINS = (
    "apnews.com",
    "bbc.com",
    "bloomberg.com",
    "cnn.com",
    "nytimes.com",
    "reuters.com",
    "theguardian.com",
    "washingtonpost.com",
)
COMMERCIAL_DOMAIN_MARKERS = (
    "tcdb.com",
    "cardboardconnection.com",
    "comc.com",
    "ebay.",
    "etsy.",
    "marketplace.",
    "shop.",
)
COMMERCIAL_TEXT_MARKERS = (
    "buy",
    "sell",
    "price guide",
    "catalog",
    "checklist",
    "coupon",
    "marketplace",
    "shopping",
    "trading card",
    "collectible",
)
SEO_MARKERS = (
    "best price",
    "click here",
    "affiliate",
    "sponsored",
    "coupon code",
    "top 10",
)
CURRENT_EVENT_MARKERS = (
    "announced",
    "confirmed",
    "passed",
    "today",
    "yesterday",
    "launch",
    "launched",
    "release",
    "released",
    "vote",
)
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "but",
    "for",
    "from",
    "has",
    "have",
    "how",
    "into",
    "new",
    "not",
    "the",
    "that",
    "this",
    "was",
    "with",
    "you",
}


def metadata(document: ContextDocument) -> dict[str, Any]:
    return document.metadata if isinstance(document.metadata, dict) else {}


def metadata_text(document: ContextDocument, key: str) -> str:
    return boundary_text(metadata(document).get(key, ""), f"{key}_text_failed").lower()


def domain(url: str) -> str:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().removeprefix("www.")


def author_domain(author: object) -> str:
    text = boundary_text(author, "post_author_text_failed").strip().lower().removeprefix("@")
    if "." not in text or text.startswith("did:"):
        return ""
    return text


def tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in TOKEN_RE.findall(text)
        if len(token) > 2 and token.lower() not in STOPWORDS
    }


def entity_tokens(text: str) -> set[str]:
    return {
        token.lower()
        for token in ENTITY_RE.findall(text)
        if len(token) > 2 and token.lower() not in STOPWORDS
    }


def safe_text(value: object) -> str:
    return boundary_text(value, "source_quality_text_failed")


def safe_texts(values: object) -> list[str]:
    items, warnings = bounded_items(values, 20, "source_quality_iter_failed")
    if warnings:
        return []
    return [safe_text(item) for item in items]


def bool_value(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def safe_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    try:
        return int(str(value))
    except Exception:
        return None


def parse_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
