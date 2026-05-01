from __future__ import annotations

import json
from datetime import UTC, datetime

from pydantic import TypeAdapter

from app.ml import diagnostics as d
from app.ml.retrieval_payload import retrieval_result_json, retrieval_result_payload
from app.schemas.domain import ContextDocument, Evidence


def retrieval_result() -> d.RetrievalResult:
    document = ContextDocument(
        id="DOC-1",
        source_type="web",
        title="Mars water context",
        url="https://example.com/mars",
        text="Hydrated minerals provide context for Mars rover evidence.",
        metadata={
            "created_at": datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
            "sanitized": True,
        },
    )
    evidence = Evidence(
        id="E1",
        document_id=document.id,
        text="Hydrated minerals provide context for Mars rover evidence.",
        score=0.75,
        source_id=document.id,
    )
    return d.make_retrieval_result(
        documents=[document],
        evidence=[evidence],
        queries=["mars rover water"],
        prompt_flags=[],
        warnings=["provider_warning"],
        private_url_blocks=[],
    )


def test_retrieval_payload_is_canonical_json_stable_and_schema_valid() -> None:
    result = retrieval_result()

    payload = retrieval_result_payload(result)
    serialized = retrieval_result_json(result)
    reloaded = json.loads(serialized)

    assert payload == reloaded
    assert payload["documents"] == [
        document.model_dump(mode="json") for document in result.documents
    ]
    assert payload["evidence"] == [item.model_dump(mode="json") for item in result.evidence]
    assert payload["diagnostics"]["warnings"] == result.warnings
    assert payload["diagnostics"]["evidence_scores"] == result.scores
    TypeAdapter(list[ContextDocument]).validate_python(payload["documents"])
    TypeAdapter(list[Evidence]).validate_python(payload["evidence"])
