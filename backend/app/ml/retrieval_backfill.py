"""Source-quality fallback evidence for retrieval misses."""

from __future__ import annotations

from collections.abc import Sequence

from app.ml import source_quality as sq
from app.ml.boundary import boundary_text, safe_limit
from app.schemas.domain import ContextDocument, Evidence


def with_quality_backfill(
    documents: Sequence[ContextDocument],
    evidence: Sequence[Evidence],
    *,
    limit: int,
) -> list[Evidence]:
    """Add primary eligible documents when vector retrieval misses them."""

    evidence_limit = safe_limit(limit)
    if evidence_limit == 0 or not evidence:
        return []
    if not all(isinstance(item, Evidence) for item in evidence):
        return list(evidence)
    merged = list(evidence)
    represented = {item.document_id for item in merged}
    for document in sorted(documents, key=_backfill_priority, reverse=True):
        if not _backfill_eligible(document):
            continue
        candidate = _backfill_evidence(document, len(merged) + 1)
        if document.id in represented:
            if document.source_type == "image":
                merged = _upgrade_represented_candidate(merged, candidate)
            continue
        merged = _merge_candidate(merged, candidate, limit=evidence_limit)
        represented.add(document.id)
    return sorted(merged, key=lambda item: item.score, reverse=True)[:evidence_limit]


def _backfill_eligible(document: ContextDocument) -> bool:
    metadata = document.metadata
    if metadata.get("citation_eligible") is not True:
        return False
    if metadata.get("citation_role") != "primary":
        return False
    if not document.text.strip():
        return False
    threshold = 0.50 if document.source_type == "image" else 0.62
    return _backfill_priority(document) >= threshold


def _backfill_priority(document: ContextDocument) -> float:
    metadata = document.metadata
    score = _metadata_float(metadata.get("source_quality_score"))
    channel = sq.source_channel_prior(document)
    direct = 0.08 if metadata.get("linked_from_post") is True else 0.0
    image = 0.18 if document.source_type == "image" else 0.0
    return min(1.0, 0.72 * score + 0.20 * channel + direct + image)


def _backfill_evidence(document: ContextDocument, index: int) -> Evidence:
    return Evidence(
        id=f"EQ{index}",
        document_id=document.id,
        source_id=document.id,
        text=boundary_text(document.text, "backfill_document_text_failed")[:1200],
        score=_backfill_priority(document),
    )


def _merge_candidate(
    evidence: list[Evidence],
    candidate: Evidence,
    *,
    limit: int,
) -> list[Evidence]:
    if len(evidence) < limit:
        return [*evidence, candidate]
    lowest = min(evidence, key=lambda item: item.score)
    if candidate.score <= lowest.score:
        return evidence
    merged = [item for item in evidence if item is not lowest]
    merged.append(candidate)
    return merged


def _upgrade_represented_candidate(
    evidence: list[Evidence],
    candidate: Evidence,
) -> list[Evidence]:
    upgraded: list[Evidence] = []
    for item in evidence:
        if item.document_id == candidate.document_id and candidate.score > item.score:
            upgraded.append(candidate)
            continue
        upgraded.append(item)
    return upgraded


def _metadata_float(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))  # type: ignore[arg-type]
    except Exception:
        return 0.0
