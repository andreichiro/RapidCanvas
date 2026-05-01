"""Canonical JSON-stable payload helpers for Dev B retrieval results."""

from __future__ import annotations

import json
from typing import Any

from app.ml.diagnostics import RetrievalResult


def retrieval_result_payload(result: RetrievalResult) -> dict[str, Any]:
    return {
        "documents": [document.model_dump(mode="json") for document in result.documents],
        "evidence": [item.model_dump(mode="json") for item in result.evidence],
        "warnings": list(result.warnings),
        "guardrail_flags": list(result.guardrail_flags),
        "source_ids": list(result.source_ids),
        "scores": dict(result.scores),
        "queries": list(result.queries),
        "private_url_blocks": list(result.private_url_blocks),
        "diagnostics": {
            "prompt_injection_flags": list(result.diagnostics.prompt_injection_flags),
            "warnings": list(result.diagnostics.warnings),
            "source_ids": list(result.diagnostics.source_ids),
            "evidence_scores": dict(result.diagnostics.evidence_scores),
            "private_url_blocks": list(result.diagnostics.private_url_blocks),
            "search_queries": list(result.diagnostics.search_queries),
            "document_count": result.diagnostics.document_count,
            "evidence_count": result.diagnostics.evidence_count,
        },
    }


def retrieval_result_json(result: RetrievalResult) -> str:
    return json.dumps(retrieval_result_payload(result), ensure_ascii=True, sort_keys=True)
