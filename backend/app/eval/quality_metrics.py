"""Deterministic source quality and usefulness metrics for eval artifacts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from app.eval.dataset import EvalCase
from app.eval.image_metrics import image_evidence_used
from app.eval.provider_quality import trace_provider_quality_score
from app.eval.quality_policy import (
    answer_usefulness_score,
    expected_guardrail,
    image_required,
    public_live_quality_pass,
)
from app.eval.source_screening import citation_ineligible_source, commercial_or_scraper_source

INJECTION_TERMS = (
    "ignore previous",
    "system prompt",
    "developer message",
    "api key",
    "do not cite",
    "disable citations",
    "delete all",
    "delete this",
    "delete post",
)
STOPWORDS = {
    "about",
    "after",
    "also",
    "because",
    "before",
    "being",
    "beyond",
    "claim",
    "claims",
    "context",
    "could",
    "does",
    "from",
    "have",
    "into",
    "only",
    "post",
    "rather",
    "should",
    "source",
    "sources",
    "that",
    "their",
    "there",
    "this",
    "thread",
    "through",
    "treat",
    "uses",
    "when",
    "where",
    "which",
    "with",
    "without",
}


def quality_metrics_for_prediction(
    case: EvalCase,
    prediction: dict[str, Any],
    *,
    point_recall: float,
    citation_coverage: float,
    unsupported_count: int = 0,
) -> dict[str, float | int]:
    """Score deterministic source relevance and answer usefulness for one prediction."""
    source_relevance = source_relevance_score(case, prediction)
    citation_relevance = citation_relevance_score(prediction)
    off_topic_count = off_topic_source_count(case, prediction)
    ineligible_citations = ineligible_citation_count(prediction)
    provider_quality = trace_provider_quality_score(_trace(prediction))
    required_image = image_required(case)
    image_used = image_evidence_used(case, prediction)
    fallback = _fallback_mode(prediction)
    guardrail_expected = expected_guardrail(case)
    safe_output = _safe_output(prediction)
    usefulness = answer_usefulness_score(
        point_recall=point_recall,
        citations=citation_coverage,
        citation_relevance=citation_relevance,
        source_relevance=source_relevance,
        off_topic_count=off_topic_count,
        fallback=fallback,
        safe_output=safe_output,
        unsupported_count=unsupported_count,
        bullet_count=len(prediction.get("bullets", [])),
        image_required=required_image,
        image_used=image_used,
        expected_guardrail=guardrail_expected,
    )
    return {
        "source_relevance_score": source_relevance,
        "citation_relevance_score": citation_relevance,
        "off_topic_source_count": off_topic_count,
        "ineligible_citation_count": ineligible_citations,
        "answer_usefulness_score": usefulness,
        "public_live_quality_pass": public_live_quality_pass(
            case=case,
            usefulness=usefulness,
            point_recall=point_recall,
            citation_coverage=citation_coverage,
            source_relevance=source_relevance,
            citation_relevance=citation_relevance,
            off_topic_count=off_topic_count,
            unsupported_count=unsupported_count,
            safe_output=safe_output,
            snippet_only_citations=_all_citations_snippet_only(prediction),
            ineligible_citation_count=ineligible_citations,
            image_required=required_image,
            image_used=image_used,
            expected_guardrail=guardrail_expected,
            provider_quality_score=provider_quality,
        ),
        "image_evidence_used": image_used,
        "image_expected_point_recall": point_recall if required_image else 1.0,
        "provider_quality_score": provider_quality,
    }


def _safe_output(prediction: Mapping[str, Any]) -> bool:
    output_text = _prediction_text(prediction)
    return not _contains_any(output_text, INJECTION_TERMS) and "secret" not in _normalize(
        output_text
    )


def source_relevance_score(case: EvalCase, prediction: dict[str, Any]) -> float:
    """Score whether returned sources match expected hints, points, and answer text."""

    sources = _cited_sources(prediction) or _sources(prediction)
    if not sources:
        return 0.0
    reference = " ".join(
        [
            *case.expected_source_hints,
            *case.expected_key_points,
            _post_text(prediction),
            _prediction_text(prediction),
        ]
    )
    scores = [_single_source_relevance(case, source, reference) for source in sources]
    return sum(scores) / len(scores)


def citation_relevance_score(prediction: dict[str, Any]) -> float:
    """Score whether each bullet cites at least one source sharing material terms."""

    bullets = _bullets(prediction)
    if not bullets:
        return 0.0
    sources_by_id = {
        str(source.get("id")): source
        for source in _sources(prediction)
        if source.get("id") is not None
    }
    bullet_scores: list[float] = []
    for bullet in bullets:
        source_ids = [str(source_id) for source_id in bullet.get("source_ids", [])]
        if not source_ids:
            bullet_scores.append(0.0)
            continue
        best = 0.0
        for source_id in source_ids:
            source = sources_by_id.get(source_id)
            if source is not None:
                if _explicitly_ineligible(source):
                    continue
                score = _lexical_overlap(str(bullet.get("text", "")), _source_text(source))
                best = max(best, min(score, 0.50) if _snippet_only(source) else score)
        bullet_scores.append(best)
    return sum(bullet_scores) / len(bullet_scores)


def ineligible_citation_count(prediction: dict[str, Any]) -> int:
    """Count unique cited sources explicitly marked ineligible for citations."""

    return sum(1 for source in _cited_sources(prediction) if _explicitly_ineligible(source))


def off_topic_source_count(case: EvalCase, prediction: dict[str, Any]) -> int:
    """Count cited sources that look unrelated enough to fail reviewer trust."""

    reference = " ".join(
        [
            *case.expected_source_hints,
            *case.expected_key_points,
            _post_text(prediction),
            _prediction_text(prediction),
        ]
    )
    count = 0
    for source in _cited_sources(prediction):
        if _trusted_channel_with_text(source):
            continue
        if _single_source_relevance(case, source, reference) < 0.15:
            count += 1
    return count


def _single_source_relevance(
    case: EvalCase,
    source: Mapping[str, Any],
    reference_text: str,
) -> float:
    quality_score = source.get("quality_score")
    quality = float(quality_score) if isinstance(quality_score, (int, float)) else 0.0
    text = _source_text(source)
    if commercial_or_scraper_source(source) or _explicitly_ineligible(source):
        return 0.0
    hint_hit = bool(case.expected_source_hints) and _contains_any(text, case.expected_source_hints)
    expected_overlap = _lexical_overlap(text, " ".join(case.expected_key_points))
    reference_overlap = _lexical_overlap(text, reference_text)
    channel_bonus = 0.10 if str(source.get("type")) in case.expected_context_channels else 0.0
    snippet_penalty = 0.25 if _snippet_only(source) else 0.0
    semantic_score = max(_score_bool(hint_hit), expected_overlap, reference_overlap)
    score = max(_quality_relevance_contribution(quality, semantic_score), semantic_score)
    return max(0.0, min(1.0, score + channel_bonus - snippet_penalty))


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


def _quality_relevance_contribution(quality_score: float, semantic_score: float) -> float:
    if quality_score <= 0.0:
        return 0.0
    if semantic_score >= 0.45:
        return quality_score
    if semantic_score >= 0.25:
        return min(quality_score, semantic_score + 0.15)
    if semantic_score >= 0.15:
        return min(quality_score, 0.25)
    return min(quality_score, 0.14)


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains_any(text: str, needles: tuple[str, ...] | list[str]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(needle) in normalized for needle in needles)


def _prediction_text(prediction: Mapping[str, Any]) -> str:
    return " ".join(str(bullet.get("text", "")) for bullet in _bullets(prediction))


def _fallback_mode(prediction: Mapping[str, Any]) -> str:
    return str(_trace(prediction).get("fallback_mode", "none"))


def _trace(prediction: Mapping[str, Any]) -> Mapping[str, Any]:
    trace = prediction.get("trace", {})
    return trace if isinstance(trace, Mapping) else {}


def _trusted_channel_with_text(source: Mapping[str, Any]) -> bool:
    if not str(source.get("snippet", "")).strip():
        return False
    if str(source.get("type")) in {"thread", "bluesky", "image"}:
        return True
    quality = source.get("quality_score")
    try:
        quality_score = float(quality)  # type: ignore[arg-type]
    except Exception:
        quality_score = 0.0
    domain = (urlparse(str(source.get("url", ""))).hostname or "").lower()
    return quality_score >= 0.85 and domain == "bsky.app"


def _bullets(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in prediction.get("bullets", []) if isinstance(item, dict)]


def _sources(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in prediction.get("sources", []) if isinstance(item, dict)]


def _cited_sources(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    sources_by_id = {
        str(source.get("id")): source
        for source in _sources(prediction)
        if source.get("id") is not None
    }
    cited: list[dict[str, Any]] = []
    seen: set[str] = set()
    for bullet in _bullets(prediction):
        for source_id in bullet.get("source_ids", []):
            key = str(source_id)
            if key not in seen and key in sources_by_id:
                cited.append(sources_by_id[key])
                seen.add(key)
    return cited


def _post_text(prediction: Mapping[str, Any]) -> str:
    post = prediction.get("post", {})
    return str(post.get("text", "")) if isinstance(post, Mapping) else ""


def _snippet_only(source: Mapping[str, Any]) -> bool:
    if bool(source.get("snippet_only")):
        return True
    metadata = source.get("metadata")
    return isinstance(metadata, Mapping) and bool(metadata.get("snippet_only"))


def _explicitly_ineligible(source: Mapping[str, Any]) -> bool:
    return citation_ineligible_source(source)


def _all_citations_snippet_only(prediction: Mapping[str, Any]) -> bool:
    sources_by_id = {
        str(source.get("id")): source
        for source in _sources(prediction)
        if source.get("id") is not None
    }
    cited_ids = [
        str(source_id)
        for bullet in _bullets(prediction)
        for source_id in bullet.get("source_ids", [])
    ]
    return bool(cited_ids) and all(
        _snippet_only(sources_by_id.get(source_id, {})) for source_id in cited_ids
    )


def _terms(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in STOPWORDS}


def _lexical_overlap(left: str, right: str) -> float:
    left_terms = _terms(left)
    right_terms = _terms(right)
    if not left_terms or not right_terms:
        return 0.0
    shared = left_terms & right_terms
    denominator = max(3, min(len(left_terms), len(right_terms)))
    return min(1.0, len(shared) / denominator)


def _score_bool(value: bool) -> float:
    return 1.0 if value else 0.0
