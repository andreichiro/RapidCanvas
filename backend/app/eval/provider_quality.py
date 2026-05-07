"""Provider-comparison quality helpers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.eval.source_screening import commercial_or_scraper_source

_LEGACY_DETERMINISTIC_ADAPTER = "deterministic" + "_dev"


def payload_source_relevance_score(bullets: list[Any], sources: list[Any]) -> float:
    """Score provider response source relevance without case-specific expectations."""

    if not bullets or not sources:
        return 0.0
    bullet_text = " ".join(
        str(bullet.get("text", "")) for bullet in bullets if isinstance(bullet, Mapping)
    )
    scores = [_provider_source_relevance(source, bullet_text) for source in sources]
    return sum(scores) / len(scores) if scores else 0.0


def payload_answer_usefulness_score(
    *,
    status_code: int,
    bullet_count: int,
    cited_bullet_count: int,
    source_count: int,
    fallback_mode: str | None,
    source_relevance_score: float,
) -> float:
    """Score provider response usefulness from shape and source relevance."""

    citation_coverage = cited_bullet_count / max(bullet_count, 1)
    score = (
        0.30 * _score_bool(status_code == 200)
        + 0.20 * _score_bool(3 <= bullet_count <= 5)
        + 0.20 * citation_coverage
        + 0.20 * source_relevance_score
        + 0.10 * _score_bool(source_count > 0 and fallback_mode != "abstain")
    )
    if fallback_mode in {"partial", "safe_summary"}:
        score *= 0.90
    if fallback_mode == "abstain":
        score = min(score, 0.35)
    return max(0.0, min(1.0, score))


def trace_provider_quality_score(trace: Mapping[str, Any]) -> float:
    """Score whether the provider path actually ran without fallback/provider errors."""

    flags = _text_items(trace.get("guardrail_flags", []))
    warnings = _text_items(trace.get("warnings", []))
    if any("provider_error" in item or "dspy_provider_error" in item for item in flags | warnings):
        return 0.0
    if any(_provider_fallback_warning(item) for item in flags | warnings):
        return 0.0
    adapter_value = trace.get("adapter_mode")
    if adapter_value is None:
        return 0.0
    adapter = str(adapter_value)
    if adapter == "none":
        return 1.0
    if adapter in {"deterministic_fallback", _LEGACY_DETERMINISTIC_ADAPTER}:
        return 0.75
    return 0.50


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


def _provider_source_relevance(source: Any, bullet_text: str) -> float:
    if not isinstance(source, Mapping):
        return 0.0
    if commercial_or_scraper_source(source):
        return 0.0
    return _lexical_overlap(_source_text(source), bullet_text)


def _terms(text: str) -> set[str]:
    stopwords = {"about", "and", "for", "from", "source", "sources", "that", "the", "this", "with"}
    return {
        token
        for token in re.findall(r"[a-z0-9]{3,}", text.lower())
        if token not in stopwords
    }


def _lexical_overlap(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    shared = left_terms & right_terms
    denominator = max(3, min(len(left_terms), len(right_terms)))
    return min(1.0, len(shared) / denominator)


def _text_items(value: object) -> set[str]:
    if isinstance(value, list):
        return {str(item) for item in value}
    return set()


def _provider_fallback_warning(item: str) -> bool:
    normalized = item.lower()
    return (
        normalized == "provider_openai_default_used"
        or "unknown_using_openai" in normalized
        or "_skipped:" in normalized
        or normalized.startswith("dspy_provider_unavailable:")
    )


def _score_bool(value: bool) -> float:
    return 1.0 if value else 0.0
