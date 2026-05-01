"""JSON and source-id helpers for DSPy runner outputs."""

from __future__ import annotations

import json
from collections.abc import Sequence
from math import isfinite
from typing import cast

from app.agent.untrusted import evidence_untrusted_label
from app.guardrails.output import BulletDraft, ExplanationDraft
from app.guardrails.policies import compact_text
from app.schemas.domain import Evidence, FallbackMode, PostContext, SourceType


def thread_context(post: PostContext) -> str:
    parts = [*post.parent_texts, *post.quoted_texts]
    return "\n".join(compact_text(part, limit=400) for part in parts)


def label(label_name: str, text: str) -> str:
    return f"{label_name}:\n{text}"


def evidence_json(
    evidence: Sequence[Evidence],
    document_source_types: dict[str, SourceType] | None = None,
) -> str:
    source_types = document_source_types or {}
    payload = [
        {
            "id": item.id,
            "source_id": item.source_id,
            "score": round(float_or_default(str(item.score), 0.0), 4),
            "text": label(
                evidence_untrusted_label(item, source_types),
                compact_text(item.text, limit=800),
            ),
        }
        for item in evidence
    ]
    return json.dumps(payload, allow_nan=False)


def draft_from_json(value: str) -> ExplanationDraft:
    return ExplanationDraft(bullets=[_bullet_from_mapping(item) for item in _bullet_items(value)])


def normalize_draft_source_ids(
    draft: ExplanationDraft,
    evidence: Sequence[Evidence],
) -> ExplanationDraft:
    """Accept evidence ids from model output and convert them to public source ids."""

    evidence_to_source = {item.id: item.source_id for item in evidence}
    source_ids = {item.source_id for item in evidence}
    normalized: list[BulletDraft] = []
    for bullet in draft.bullets:
        mapped_ids = [
            evidence_to_source.get(source_id, source_id)
            for source_id in bullet.source_ids
            if source_id in source_ids or source_id in evidence_to_source
        ]
        normalized.append(BulletDraft(text=bullet.text, source_ids=list(dict.fromkeys(mapped_ids))))
    return ExplanationDraft(bullets=normalized)


def fallback_mode(value: str) -> FallbackMode:
    if value in {"none", "partial", "abstain", "safe_summary"}:
        return cast(FallbackMode, value)
    return "abstain"


def json_list(value: str) -> list[str]:
    parsed = _parse_json(value)
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def json_mapping(value: str) -> dict[str, object]:
    parsed = _parse_json(value)
    return parsed if isinstance(parsed, dict) else {}


def float_or_default(value: str, default: float) -> float:
    try:
        parsed = float(value)
    except ValueError:
        return default
    return parsed if isfinite(parsed) else default


def _bullet_items(value: str) -> list[dict[str, object]]:
    parsed = _parse_json(value)
    if isinstance(parsed, dict):
        bullets = parsed.get("bullets", [])
        if isinstance(bullets, list):
            return [item for item in bullets if isinstance(item, dict)]
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    return []


def _bullet_from_mapping(item: dict[str, object]) -> BulletDraft:
    text = item.get("text")
    source_ids = item.get("source_ids", [])
    if not isinstance(text, str):
        text = ""
    if not isinstance(source_ids, list):
        source_ids = []
    return BulletDraft(
        text=text or "Empty model bullet.",
        source_ids=[str(source) for source in source_ids],
    )


def _parse_json(value: str) -> object:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
