from __future__ import annotations

from typing import Any

import pytest

from app.ml.vector_store import QdrantVectorStore


def test_qdrant_vector_store_uses_remote_url_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    class FakeQdrantModule:
        QdrantClient = FakeClient

    def fake_import_module(name: str) -> object:
        if name == "qdrant_client":
            return FakeQdrantModule
        raise AssertionError(name)

    monkeypatch.setattr("app.ml.vector_backends.importlib.import_module", fake_import_module)

    QdrantVectorStore(url="http://qdrant:6333", path="/tmp/not-used")

    assert captured == {"url": "http://qdrant:6333"}
