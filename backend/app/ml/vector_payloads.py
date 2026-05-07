"""Defensive vector-store payload normalization."""

from __future__ import annotations

import math
import uuid
from collections.abc import Mapping
from typing import Any, cast

from app.ml.boundary import boundary_attr, boundary_text


def cosine_01(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    try:
        left_values = [float(value) for value in left]
        right_values = [float(value) for value in right]
    except Exception:
        return 0.0
    if not all(math.isfinite(value) for value in [*left_values, *right_values]):
        return 0.0
    dot = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left_values))
    right_norm = math.sqrt(sum(value * value for value in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    cosine = dot / (left_norm * right_norm)
    return max(0.0, min(1.0, (cosine + 1.0) / 2.0))


def public_score(score: object) -> float:
    try:
        value = float(cast(Any, score))
    except Exception:
        return 0.0
    if math.isnan(value) or value == -math.inf:
        return 0.0
    if value == math.inf:
        return 1.0
    return max(0.0, min(1.0, value))


def payload_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def payload_value(payload: Mapping[str, object], key: str, default: object = "") -> object:
    try:
        return payload.get(key, default)
    except Exception:
        return default


def metadata_mapping(value: object) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        try:
            return dict(value)
        except Exception as exc:
            return {"metadata_iter_failed": f"metadata_iter_failed:{exc.__class__.__name__}"}
    return {"metadata": value}


def chunk_metadata(
    document: object,
    *,
    chunk_index: int,
    chunk_start: int,
    chunk_end: int,
    chunking: str,
) -> dict[str, object]:
    return {
        **metadata_mapping(boundary_attr(document, "metadata", "metadata_field_failed")),
        "chunk_index": chunk_index,
        "chunk_start": chunk_start,
        "chunk_end": chunk_end,
        "chunking": chunking,
        "source_url": boundary_text(
            boundary_attr(document, "url", "document_url_field_failed"),
            "source_url_text_failed",
        ),
        "source_type": boundary_text(
            boundary_attr(document, "source_type", "source_type_field_failed"),
            "source_type_text_failed",
        ),
        "source_title": boundary_text(
            boundary_attr(document, "title", "document_title_field_failed"),
            "source_title_text_failed",
        ),
    }


def qdrant_point_id(chunk: object, namespace: object) -> str:
    payload_key = f"{_namespace_text(namespace)}:{_chunk_text(chunk, 'id')}"
    return str(uuid.uuid5(uuid.NAMESPACE_URL, payload_key))


def qdrant_payload(chunk: object, namespace: object) -> dict[str, object]:
    return {
        "namespace": _namespace_text(namespace),
        "chunk_id": _chunk_text(chunk, "id"),
        "document_id": _chunk_text(chunk, "document_id"),
        "source_id": _chunk_text(chunk, "source_id"),
        "text": _chunk_text(chunk, "text"),
        "metadata": metadata_mapping(
            boundary_attr(chunk, "metadata", "chunk_metadata_field_failed")
        ),
    }


def _chunk_text(chunk: object, name: str) -> str:
    return boundary_text(
        boundary_attr(chunk, name, f"chunk_{name}_field_failed"),
        f"chunk_{name}_text_failed",
    )


def _namespace_text(namespace: object) -> str:
    return boundary_text(namespace, "namespace_text_failed") or "default"
