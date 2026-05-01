"""Final C2 retrieval payload safety policy."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from app.guardrails.identifiers import safe_identifier
from app.guardrails.prompt_injection import PromptInjectionScanner, sanitize_untrusted_text
from app.ml.boundary import boundary_attr, boundary_text, bounded_items
from app.schemas.domain import ContextDocument, Evidence

_MAX_DIAGNOSTIC_ITEMS = 50


@dataclass(frozen=True)
class SafeEvidenceResult:
    evidence: list[Evidence]
    warnings: list[str]
    prompt_flags: list[str]


@dataclass(frozen=True)
class _EvidenceCandidate:
    evidence: Evidence | None
    warnings: list[str]


@dataclass(frozen=True)
class _EvidenceScanResult:
    warnings: list[str]
    prompt_flags: list[str]


def diagnostic_text(value: object) -> str:
    return boundary_text(value, "diagnostic_text_failed")


def diagnostic_strings(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str | bytes | bytearray):
        return [diagnostic_text(value)]
    if isinstance(value, Mapping):
        return [boundary_text(value, "diagnostic_text_failed")]
    if isinstance(value, Iterable):
        return _iterable_diagnostic_strings(value)
    return [boundary_text(value, "diagnostic_text_failed")]


def _iterable_diagnostic_strings(value: Iterable[object]) -> list[str]:
    texts: list[str] = []
    items, warnings = bounded_items(value, _MAX_DIAGNOSTIC_ITEMS, "diagnostic_iter_failed")
    for item in items:
        if text := diagnostic_text(item):
            texts.append(text)
    return [*texts, *warnings]


def unique_documents_by_id(documents: Sequence[ContextDocument]) -> list[ContextDocument]:
    seen: dict[str, int] = {}
    unique_documents: list[ContextDocument] = []
    for document in documents:
        document_id = safe_identifier(
            boundary_attr(document, "id", "document_id_field_failed"),
            prefix="DOC",
        )
        count = seen.get(document_id, 0)
        seen[document_id] = count + 1
        if count:
            document = document.model_copy(update={"id": f"{document_id}-{count + 1}"})
        unique_documents.append(document)
    return unique_documents


def safe_evidence_for_documents(
    evidence: object,
    documents: Sequence[ContextDocument],
    scanner: PromptInjectionScanner | None = None,
) -> SafeEvidenceResult:
    document_ids = {
        diagnostic_text(boundary_attr(document, "id", "document_id_field_failed"))
        for document in documents
    }
    evidence_items, evidence_warnings = bounded_items(
        evidence, _MAX_DIAGNOSTIC_ITEMS, "retrieval_evidence_iter_failed"
    )
    active_scanner = scanner or PromptInjectionScanner()
    seen_ids: set[str] = set()
    safe_evidence: list[Evidence] = []
    warnings: list[str] = list(evidence_warnings)
    prompt_flags: list[str] = []
    for index, item in enumerate(evidence_items, start=1):
        candidate = _safe_evidence_candidate(item, index, document_ids, seen_ids)
        warnings.extend(candidate.warnings)
        if candidate.evidence is None:
            continue
        scan_result = _scan_evidence_text(candidate.evidence, active_scanner)
        warnings.extend(scan_result.warnings)
        prompt_flags.extend(scan_result.prompt_flags)
        safe_evidence.append(candidate.evidence)
        seen_ids.add(candidate.evidence.id)
    return SafeEvidenceResult(safe_evidence, warnings, prompt_flags)


def _safe_evidence_candidate(
    item: object,
    index: int,
    document_ids: set[str],
    seen_ids: set[str],
) -> _EvidenceCandidate:
    if not isinstance(item, Evidence):
        return _EvidenceCandidate(None, [f"retrieval_evidence_invalid_item:{index}"])
    item_id = safe_identifier(
        boundary_attr(item, "id", "evidence_id_field_failed"), prefix="EVID"
    )
    document_id = diagnostic_text(
        boundary_attr(item, "document_id", "evidence_document_id_field_failed")
    )
    source_id = diagnostic_text(boundary_attr(item, "source_id", "evidence_source_id_field_failed"))
    text = sanitize_untrusted_text(
        diagnostic_text(boundary_attr(item, "text", "evidence_text_field_failed"))
    )
    if not item_id:
        return _EvidenceCandidate(None, [f"retrieval_evidence_invalid_item:{index}"])
    if item_id in seen_ids:
        return _EvidenceCandidate(None, [f"retrieval_evidence_duplicate:{item_id}"])
    if document_id not in document_ids or source_id not in document_ids:
        return _EvidenceCandidate(None, [f"retrieval_evidence_orphaned:{item_id}"])
    if not text.strip():
        return _EvidenceCandidate(None, [f"retrieval_evidence_empty_text:{item_id}"])
    score, score_warning = _safe_evidence_score(
        boundary_attr(item, "score", "evidence_score_field_failed"), item_id
    )
    warnings = [score_warning] if score_warning else []
    return _EvidenceCandidate(
        Evidence(
            id=item_id,
            document_id=document_id,
            text=text,
            score=score,
            source_id=source_id,
        ),
        warnings,
    )


def _scan_evidence_text(
    evidence: Evidence,
    scanner: PromptInjectionScanner,
) -> _EvidenceScanResult:
    scan = scanner.scan(evidence.text, label="UNTRUSTED_EVIDENCE")
    warnings = [
        f"prompt_injection_risk:{evidence.source_id}:{flag}"
        for flag in scan.flags
    ]
    return _EvidenceScanResult(warnings, list(scan.flags))


def _safe_evidence_score(score: object, evidence_id: str) -> tuple[float, str]:
    try:
        value = float(cast(Any, score))
    except Exception:
        return 0.0, f"retrieval_evidence_invalid_score:{evidence_id}"
    if math.isnan(value) or value == -math.inf:
        return 0.0, f"retrieval_evidence_nonfinite_score:{evidence_id}"
    if value == math.inf:
        return 1.0, f"retrieval_evidence_nonfinite_score:{evidence_id}"
    return max(0.0, min(1.0, value)), ""
