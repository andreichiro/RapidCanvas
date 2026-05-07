"""Image-specific eval metrics for live-quality proof."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from app.eval.dataset import EvalCase
from app.eval.quality_policy import image_required
from app.eval.source_screening import citation_ineligible_source


def image_evidence_used(case: EvalCase, prediction: dict[str, Any]) -> float:
    """Return 1 when image-required cases cite usable image evidence."""

    if not image_required(case):
        return 1.0
    image_source_ids = {
        str(source.get("id"))
        for source in _sources(prediction)
        if (
            str(source.get("type")) == "image"
            and source.get("id") is not None
            and _usable_image_source(source)
        )
    }
    if not image_source_ids:
        return 0.0
    cited_ids = {
        str(source_id)
        for bullet in _bullets(prediction)
        for source_id in bullet.get("source_ids", [])
    }
    return 1.0 if image_source_ids & cited_ids else 0.0


def _usable_image_source(source: Mapping[str, Any]) -> bool:
    if citation_ineligible_source(source):
        return False
    text = _normalize(_source_text(source))
    empty_markers = {
        "image was present but had no alt text",
        "vision unavailable",
        "no image description available",
    }
    return bool(text) and not any(marker in text for marker in empty_markers)


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


def _bullets(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in prediction.get("bullets", []) if isinstance(item, dict)]


def _sources(prediction: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [item for item in prediction.get("sources", []) if isinstance(item, dict)]


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
