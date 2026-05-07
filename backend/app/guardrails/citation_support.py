"""Deterministic citation support checks for factual explanation bullets."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{1,}")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_MONTH_DATE_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?)\s+\d{1,2}(?:,\s*(?:19|20)\d{2})?\b",
    re.IGNORECASE,
)
_ENTITY_RE = re.compile(r"\b[A-Z][A-Za-z0-9.+#-]*(?:\s+[A-Z][A-Za-z0-9.+#-]*)*\b")
_CLAIM_MARKERS = (
    "because",
    "means",
    "refers to",
    "was created by",
    "announced",
    "passed",
    "confirmed",
    "changed",
    "created",
    "launched",
)
_CLAIM_SUPPORT_MARKERS = {
    "because": ("because", "caused", "due to", "reason", "so that"),
    "means": ("means", "meaning", "defined", "definition", "refers to", "stands for"),
    "refers to": ("refers to", "means", "defined", "definition", "stands for"),
    "was created by": ("created by", "founded by", "made by", "authored by"),
    "announced": ("announced", "announcement", "said", "introduced", "unveiled"),
    "passed": ("passed", "approved", "adopted", "enacted", "voted"),
    "confirmed": ("confirmed", "verified", "said", "announced"),
    "changed": ("changed", "change", "changes", "updated", "revised", "replaced"),
    "created": ("created", "creation", "founded", "formed", "launched"),
    "launched": ("launched", "launch", "introduced", "released", "started"),
}
_STOPWORDS = {
    "about",
    "abstention",
    "after",
    "answer",
    "and",
    "are",
    "available",
    "because",
    "but",
    "cited",
    "context",
    "contained",
    "contains",
    "content",
    "credential-seeking",
    "does",
    "beyond",
    "echoed",
    "english",
    "evidence",
    "expand",
    "external",
    "fallback",
    "for",
    "from",
    "has",
    "have",
    "instruction-like",
    "into",
    "limited",
    "not",
    "partial",
    "post",
    "present",
    "request",
    "safe",
    "source-backed",
    "summary",
    "supported",
    "that",
    "the",
    "this",
    "text",
    "translate",
    "unsafe",
    "was",
    "visible",
    "with",
}
_ENTITY_STOPWORDS = _STOPWORDS | {
    "A",
    "An",
    "As",
    "It",
    "No",
    "Partial",
    "Safe",
    "Source",
    "Source-backed",
    "Supported",
    "The",
}


@dataclass(frozen=True)
class CitationSupportResult:
    """Support status and issue labels for one bullet."""

    is_supported: bool
    issues: list[str] = field(default_factory=list)


def check_bullet_support(
    bullet_text: str,
    source_ids: list[str],
    source_text_by_id: dict[str, str],
    *,
    snippet_only_source_ids: set[str] | None = None,
) -> CitationSupportResult:
    """Check that cited source text materially supports the bullet."""

    if not source_ids:
        return CitationSupportResult(False, ["uncited_output"])
    cited_text_by_id = {source_id: source_text_by_id.get(source_id, "") for source_id in source_ids}
    cited_text = " ".join(cited_text_by_id.values())
    if not cited_text.strip():
        if _empty_source_fallback_supported(bullet_text, source_ids, source_text_by_id):
            return CitationSupportResult(True, [])
        return CitationSupportResult(False, ["unknown_citation"])

    bullet_terms = _material_terms(bullet_text)
    source_terms = _material_terms(cited_text)
    shared_terms = bullet_terms & source_terms
    issues = _support_issues(
        bullet_text,
        bullet_terms,
        source_terms,
        shared_terms,
        cited_text,
        cited_text_by_id,
        source_ids,
        snippet_only_source_ids or set(),
    )
    return CitationSupportResult(not issues, issues)


def validate_bullet_support(
    bullets: Iterable[tuple[str, list[str]]],
    source_text_by_id: dict[str, str],
    *,
    snippet_only_source_ids: set[str] | None = None,
) -> list[str]:
    """Return deduped support labels for a sequence of bullets."""

    issues: list[str] = []
    for text, source_ids in bullets:
        issues.extend(
            check_bullet_support(
                text,
                source_ids,
                source_text_by_id,
                snippet_only_source_ids=snippet_only_source_ids,
            ).issues
        )
    return _dedupe(issues)


def _support_issues(
    bullet_text: str,
    bullet_terms: set[str],
    source_terms: set[str],
    shared_terms: set[str],
    cited_text: str,
    cited_text_by_id: dict[str, str],
    source_ids: list[str],
    snippet_only_source_ids: set[str],
) -> list[str]:
    if _low_evidence_meta_supported(bullet_text, cited_text, shared_terms):
        return []
    issues: list[str] = []
    if _shared_ratio(bullet_terms, shared_terms) < 0.34:
        issues.extend(["weak_citation_support", "off_topic_citation"])
    if _missing_dates(bullet_text, cited_text):
        issues.append("unsupported_claim")
    if _missing_entity_terms(bullet_text, source_terms):
        issues.extend(["weak_citation_support", "off_topic_citation"])
    if _unsupported_claim_marker(bullet_text, cited_text):
        issues.append("unsupported_claim")
    if _requires_support(bullet_text) and len(shared_terms) < 2:
        issues.append("unsupported_claim")
    if _snippet_only_causal_claim(
        bullet_text,
        source_ids,
        snippet_only_source_ids,
        cited_text_by_id,
    ):
        issues.append("needs_primary_source")
    return _dedupe(issues)


def _low_evidence_meta_supported(
    bullet_text: str,
    cited_text: str,
    shared_terms: set[str],
) -> bool:
    """Allow conservative meta-summaries when the cited post is visibly sparse."""

    source_terms = _material_terms(cited_text)
    if not cited_text.strip() or len(source_terms) > 3 or not shared_terms:
        return False
    lowered = bullet_text.lower()
    meta_markers = (
        "sparse context",
        "visible post",
        "only says",
        "not enough context",
        "no broader claim",
        "safe summary",
    )
    return any(marker in lowered for marker in meta_markers)


def _material_terms(text: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in [*_TOKEN_RE.findall(text), *_YEAR_RE.findall(text)]
        if len(_normalize_token(token)) > 2 and _normalize_token(token) not in _STOPWORDS
    }


def _date_tokens(text: str) -> set[str]:
    return {
        re.sub(r"\s+", " ", token.lower()).strip(", ")
        for token in [*_YEAR_RE.findall(text), *_MONTH_DATE_RE.findall(text)]
    }


def _missing_dates(bullet_text: str, cited_text: str) -> bool:
    bullet_dates = _date_tokens(bullet_text)
    return bool(bullet_dates) and not bullet_dates <= _date_tokens(cited_text)


def _missing_entity_terms(bullet_text: str, source_terms: set[str]) -> bool:
    entity_terms = _named_entity_terms(bullet_text)
    return bool(entity_terms) and not entity_terms <= source_terms


def _named_entity_terms(text: str) -> set[str]:
    terms: set[str] = set()
    for match in _ENTITY_RE.finditer(text):
        tokens = [
            _normalize_token(token)
            for token in _TOKEN_RE.findall(match.group(0))
            if _entity_token_is_material(token)
        ]
        terms.update(tokens)
    return terms


def _entity_token_is_material(token: str) -> bool:
    lowered = _normalize_token(token)
    if (
        token in _ENTITY_STOPWORDS
        or lowered in _ENTITY_STOPWORDS
        or lowered in {"source", "source-backed", "supported"}
    ):
        return False
    return len(token) > 2 or token.isupper()


def _normalize_token(token: str) -> str:
    return token.lower().strip(".,:;!?")


def _unsupported_claim_marker(bullet_text: str, cited_text: str) -> bool:
    lowered_bullet = bullet_text.lower()
    lowered_source = cited_text.lower()
    return any(
        marker in lowered_bullet
        and not any(support in lowered_source for support in support_markers)
        for marker, support_markers in _CLAIM_SUPPORT_MARKERS.items()
    )


def _shared_ratio(bullet_terms: set[str], shared_terms: set[str]) -> float:
    if not bullet_terms:
        return 1.0
    return len(shared_terms) / len(bullet_terms)


def _requires_support(text: str) -> bool:
    lowered = text.lower()
    return bool(_YEAR_RE.search(text)) or any(marker in lowered for marker in _CLAIM_MARKERS)


def _snippet_only_causal_claim(
    bullet_text: str,
    source_ids: list[str],
    snippet_only_source_ids: set[str],
    cited_text_by_id: dict[str, str],
) -> bool:
    if not source_ids or not any(source_id in snippet_only_source_ids for source_id in source_ids):
        return False
    if not (_requires_support(bullet_text) or "history" in bullet_text.lower()):
        return False
    primary_text = " ".join(
        text
        for source_id, text in cited_text_by_id.items()
        if source_id not in snippet_only_source_ids
    )
    if not primary_text.strip():
        return True
    return not _text_supports_material_claim(bullet_text, primary_text)


def _text_supports_material_claim(bullet_text: str, source_text: str) -> bool:
    bullet_terms = _material_terms(bullet_text)
    source_terms = _material_terms(source_text)
    shared_terms = bullet_terms & source_terms
    if _shared_ratio(bullet_terms, shared_terms) < 0.34:
        return False
    if _missing_dates(bullet_text, source_text):
        return False
    if _missing_entity_terms(bullet_text, source_terms):
        return False
    if _unsupported_claim_marker(bullet_text, source_text):
        return False
    return not (_requires_support(bullet_text) and len(shared_terms) < 2)


def _empty_source_fallback_supported(
    bullet_text: str,
    source_ids: list[str],
    source_text_by_id: dict[str, str],
) -> bool:
    if any(source_id not in source_text_by_id for source_id in source_ids):
        return False
    if any(source_text_by_id[source_id].strip() for source_id in source_ids):
        return False
    normalized = " ".join(_TOKEN_RE.findall(bullet_text.lower()))
    return "visible post has no text" in normalized


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
