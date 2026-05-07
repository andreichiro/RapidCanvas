from __future__ import annotations

from datetime import UTC, datetime
from inspect import signature
from pathlib import Path
from typing import Any, cast

import pytest

from app.ml.diagnostics import RetrievalDiagnostics
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, QdrantVectorStore
from app.schemas.domain import ContextDocument, Evidence, PostContext


def test_production_vector_code_never_recreates_or_deletes_shared_collections() -> None:
    app_root = Path(__file__).resolve().parents[2]
    files = [
        app_root / "ml" / "rag_runtime.py",
        app_root / "ml" / "retrieval_service.py",
        app_root / "ml" / "vector_backends.py",
        app_root / "ml" / "vector_payloads.py",
        app_root / "ml" / "vector_store.py",
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        assert "recreate_collection(" not in text
        assert "delete_collection(" not in text


def test_vector_backend_contract_requires_namespace_lifecycle() -> None:
    for backend in (InMemoryVectorStore, QdrantVectorStore):
        assert "vector_size" in signature(backend.ensure_collection).parameters
        assert "namespace" in signature(backend.upsert).parameters
        assert "namespace" in signature(backend.query).parameters
        assert "namespace" in signature(backend.clear_namespace).parameters


@pytest.mark.asyncio
async def test_retrieval_service_passes_post_scoped_namespace_to_rag() -> None:
    rag_service = RecordingRagService()
    service = RetrievalService(
        rag_service=cast(Any, rag_service),
        settings=RetrievalSettings(
            include_thread_context=True,
            include_linked_pages=False,
            include_search=False,
        ),
    )

    await service.retrieve(_post("alpha"), queries=["same query"])
    await service.retrieve(_post("beta"), queries=["same query"])
    stable_prefixes = [namespace.rsplit("-", 1)[0] for namespace in rag_service.namespaces]

    assert len(rag_service.namespaces) == 2
    assert all(namespace.startswith("retrieval-") for namespace in rag_service.namespaces)
    assert stable_prefixes[0] != stable_prefixes[1]


class RecordingRagService:
    last_diagnostics = RetrievalDiagnostics()

    def __init__(self) -> None:
        self.namespaces: list[str] = []

    def retrieve(
        self,
        query: str,
        documents: list[ContextDocument],
        *,
        namespace: str | None = None,
    ) -> list[Evidence]:
        del query
        self.namespaces.append(namespace or "")
        if not documents:
            return []
        document = documents[0]
        return [
            Evidence(
                id="E1",
                document_id=document.id,
                source_id=document.id,
                text=document.text,
                score=0.9,
            )
        ]


def _post(key: str) -> PostContext:
    return PostContext(
        url=f"https://bsky.app/profile/example.com/post/{key}",
        at_uri=f"at://did:plc:example/app.bsky.feed.post/{key}",
        author="example.com",
        text="The post asks for the same retrieval evidence.",
        created_at=datetime(2026, 5, 6, tzinfo=UTC),
    )
