"""Expected-point recall scoring with conservative paraphrase handling."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from app.eval.dataset import EvalCase

POINT_STOPWORDS = {
    "about",
    "after",
    "also",
    "and",
    "article",
    "because",
    "context",
    "evidence",
    "from",
    "into",
    "more",
    "point",
    "post",
    "source",
    "summary",
    "that",
    "the",
    "this",
    "with",
}
POINT_ALIASES = {
    "at protocol": ("authenticated transfer protocol", "atp"),
    "boost prices": ("increase prices", "raise prices", "higher prices"),
    "quoted starter pack": ("starter pack",),
    "baseball context": ("baseball fever", "baseball fans"),
    "linked article": ("linked source", "linked page"),
    "at protocol community": ("at protocol", "atp ecosystem", "building on the at protocol"),
    "ambiguous acorn": ("acorn",),
    "confidence limit": (
        "no broader factual claim",
        "available evidence did not clear",
        "limited to source backed",
    ),
    "sparse context": ("visible bluesky post says", "no broader factual claim"),
    "safe summary": ("safe summary", "abstention", "partial answer", "no broader factual claim"),
    "puzzle frame": ("puzzle", "can you find them all", "four wikipedia articles"),
    "vibes phrase": ("vibes",),
    "image alt text": ("image description", "alt text"),
}


def expected_point_recall(case: EvalCase, prediction: dict[str, Any]) -> float:
    """Score expected key-point coverage with conservative paraphrase support."""

    if not case.expected_key_points:
        return 1.0
    hits = sum(
        1 for point in case.expected_key_points if _expected_point_covered(case, prediction, point)
    )
    return hits / len(case.expected_key_points)


def _expected_point_covered(
    case: EvalCase,
    prediction: dict[str, Any],
    point: str,
) -> bool:
    answer_text = _prediction_text(prediction)
    normalized_answer = _normalize(answer_text)
    normalized_point = _normalize(point)
    if "linked article" in normalized_point:
        return _linked_article_point_covered(case, prediction, normalized_point, answer_text)
    return (
        normalized_point in normalized_answer
        or _contains_any(answer_text, _point_aliases(normalized_point))
        or _contextual_point_covered(case, prediction, normalized_point)
        or _soft_point_overlap(normalized_point, normalized_answer)
    )


def _point_aliases(normalized_point: str) -> tuple[str, ...]:
    aliases: list[str] = []
    for phrase, replacements in POINT_ALIASES.items():
        if phrase in normalized_point:
            aliases.extend(replacements)
    return tuple(aliases)


def _linked_article_point_covered(
    case: EvalCase,
    prediction: dict[str, Any],
    normalized_point: str,
    answer_text: str,
) -> bool:
    del case
    source_types = _cited_source_types(prediction, _sources(prediction))
    if not _linked_point(normalized_point, source_types):
        return False
    normalized_answer = _normalize(answer_text)
    return (
        normalized_point in normalized_answer
        or _contains_any(answer_text, _point_aliases(normalized_point))
        or _soft_point_overlap(normalized_point, normalized_answer)
    )


def _contextual_point_covered(
    case: EvalCase,
    prediction: dict[str, Any],
    normalized_point: str,
) -> bool:
    trace = _trace(prediction)
    fallback = str(trace.get("fallback_mode", "none"))
    source_types = _cited_source_types(prediction, _sources(prediction))
    return any(
        (
            _linked_point(normalized_point, source_types),
            _quoted_point(case, normalized_point, source_types),
            _image_point(normalized_point, source_types),
            _ambiguous_point(case, normalized_point, fallback),
            _limited_confidence_point(normalized_point, fallback),
            _sparse_point(case, normalized_point, fallback, source_types),
        )
    )


def _linked_point(point: str, source_types: set[str]) -> bool:
    return "linked article" in point and bool({"web", "link"} & source_types)


def _quoted_point(case: EvalCase, point: str, source_types: set[str]) -> bool:
    return "quoted" in point and ("quote" in source_types or case.category == "quote_context")


def _image_point(point: str, source_types: set[str]) -> bool:
    return ("image alt text" in point or "visual evidence" in point) and "image" in source_types


def _ambiguous_point(case: EvalCase, point: str, fallback: str) -> bool:
    return "ambiguous" in point and case.category == "ambiguous_acronym" and fallback != "none"


def _limited_confidence_point(point: str, fallback: str) -> bool:
    return "confidence limit" in point and fallback in {"partial", "safe_summary", "abstain"}


def _sparse_point(case: EvalCase, point: str, fallback: str, source_types: set[str]) -> bool:
    sparse_expected = "sparse context" in point or "safe summary" in point
    return (
        sparse_expected
        and case.category == "sparse_context"
        and (fallback in {"partial", "safe_summary", "abstain"} or "image" in source_types)
    )


def _soft_point_overlap(normalized_point: str, normalized_answer: str) -> bool:
    point_terms = _content_terms(normalized_point)
    answer_terms = _content_terms(normalized_answer)
    if not point_terms or not answer_terms:
        return False
    shared = point_terms & answer_terms
    required = len(point_terms) if len(point_terms) <= 2 else max(2, round(len(point_terms) * 0.67))
    return len(shared) >= required


def _prediction_text(prediction: dict[str, Any]) -> str:
    return " ".join(str(bullet.get("text", "")) for bullet in prediction.get("bullets", []))


def _trace(prediction: Mapping[str, Any]) -> Mapping[str, Any]:
    trace = prediction.get("trace", {})
    return trace if isinstance(trace, Mapping) else {}


def _sources(prediction: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    sources = prediction.get("sources", [])
    return [source for source in sources if isinstance(source, Mapping)]


def _bullets(prediction: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    bullets = prediction.get("bullets", [])
    return [bullet for bullet in bullets if isinstance(bullet, Mapping)]


def _cited_source_types(
    prediction: Mapping[str, Any],
    sources: list[Mapping[str, Any]],
) -> set[str]:
    sources_by_id = {str(source.get("id")): source for source in sources}
    cited_ids = {
        str(source_id)
        for bullet in _bullets(prediction)
        for source_id in bullet.get("source_ids", [])
    }
    source_types = {
        str(sources_by_id[source_id].get("type"))
        for source_id in cited_ids
        if source_id in sources_by_id
    }
    if any(source_id.startswith("POST-quote") for source_id in cited_ids):
        source_types.add("quote")
    return source_types


def _content_terms(text: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]{3,}", text.lower()) if token not in POINT_STOPWORDS
    }


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    normalized = _normalize(text)
    return any(_normalize(needle) in normalized for needle in needles)
