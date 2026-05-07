"""Source-quality bridge helpers for GEPA eval examples."""

from __future__ import annotations

from typing import Any

SOURCE_QUALITY_POLICY_VERSION = "source_quality_v1"


def source_quality_summary(
    sources: list[dict[str, Any]],
    citation_source_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Return expected citation relevance and source-quality scores."""

    by_id = {str(source.get("id", "")): source for source in sources if source.get("id")}
    eligible_source_ids = tuple(
        source_id for source_id, source in by_id.items() if source_citation_eligible(source)
    )
    citation_eligible_ids = tuple(
        source_id for source_id in citation_source_ids if source_id in eligible_source_ids
    )
    citation_relevance = (
        round(len(citation_eligible_ids) / len(citation_source_ids), 3)
        if citation_source_ids
        else 1.0
    )
    cited_scores = [
        source_quality_score(by_id[source_id])
        for source_id in citation_source_ids
        if source_id in by_id
    ]
    source_scores = [source_quality_score(source) for source in sources]
    return {
        "citation_eligible_source_ids": citation_eligible_ids,
        "expected_citation_relevance_score": citation_relevance,
        "expected_source_quality_score": average_score(cited_scores or source_scores or [1.0]),
    }


def source_quality_score(source: dict[str, Any]) -> float:
    """Return fixture source-quality score, with deterministic defaults."""

    metadata = _mapping(source.get("metadata", {}))
    for value in (
        source.get("quality_score"),
        source.get("source_quality_score"),
        metadata.get("source_quality_score"),
        metadata.get("quality_score"),
    ):
        if value is None:
            continue
        try:
            return round(max(0.0, min(1.0, float(value))), 3)
        except (TypeError, ValueError):
            continue
    source_type = str(source.get("type", "")).lower()
    if source_type in {"thread", "bluesky", "quote", "target"}:
        return 0.78
    if source_type == "image":
        return 0.76
    return 0.72


def source_quality_reasons(source: dict[str, Any]) -> list[str]:
    """Return fixture quality reasons or a deterministic fallback reason."""

    metadata = _mapping(source.get("metadata", {}))
    reasons = _string_list(source.get("quality_reasons", []))
    if not reasons:
        reasons = _string_list(source.get("source_quality_reasons", []))
    if not reasons:
        reasons = _string_list(metadata.get("source_quality_reasons", []))
    if reasons:
        return reasons
    source_type = str(source.get("type", "")).lower()
    return [f"fixture_{source_type or 'source'}_evidence"]


def source_citation_eligible(source: dict[str, Any]) -> bool:
    """Return whether a fixture source is expected to be citation-eligible."""

    metadata = _mapping(source.get("metadata", {}))
    for value in (
        source.get("citation_eligible"),
        metadata.get("citation_eligible"),
    ):
        if isinstance(value, bool):
            return value
    return source_quality_score(source) >= 0.55


def average_score(values: list[float]) -> float:
    """Return a stable rounded score average."""

    if not values:
        return 0.0
    return round(sum(values) / len(values), 3)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
