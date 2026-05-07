"""Namespace-aware vector-store backends."""

from __future__ import annotations

import importlib
import re
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock, local
from typing import Any, Protocol, cast

from app.ml.boundary import boundary_text, safe_limit
from app.ml.vector_payloads import (
    cosine_01,
    metadata_mapping,
    payload_mapping,
    payload_value,
    public_score,
    qdrant_payload,
    qdrant_point_id,
)


@dataclass(frozen=True)
class DocumentChunk:
    id: str
    document_id: str
    source_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VectorSearchResult:
    chunk: DocumentChunk
    score: float


class VectorStore(Protocol):
    def ensure_collection(self, vector_size: int) -> None: ...

    def upsert(
        self,
        namespace: str,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[list[float]],
    ) -> None: ...

    def query(
        self,
        namespace: str,
        embedding: list[float],
        limit: int,
    ) -> list[VectorSearchResult]: ...

    def clear_namespace(self, namespace: str) -> None: ...


class InMemoryVectorStore:
    backend_name = "in_memory_fallback"

    def __init__(self) -> None:
        self._items_by_namespace: dict[str, list[tuple[DocumentChunk, list[float]]]] = {}
        self._lock = RLock()

    def ensure_collection(self, vector_size: int) -> None:
        del vector_size

    def upsert(
        self,
        namespace: str,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[list[float]],
    ) -> None:
        with self._lock:
            self._items_by_namespace.setdefault(namespace, []).extend(
                (chunk, embedding) for chunk, embedding in zip(chunks, embeddings, strict=True)
            )

    def query(
        self,
        namespace: str,
        embedding: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        limit_value = safe_limit(limit)
        if limit_value == 0:
            return []
        with self._lock:
            items = list(self._items_by_namespace.get(namespace, ()))
        results = [
            VectorSearchResult(chunk=chunk, score=cosine_01(embedding, stored_embedding))
            for chunk, stored_embedding in items
        ]
        return sorted(results, key=lambda result: result.score, reverse=True)[:limit_value]

    def clear_namespace(self, namespace: str) -> None:
        with self._lock:
            self._items_by_namespace.pop(namespace, None)

    def namespace_items(self, namespace: str) -> list[tuple[DocumentChunk, list[float]]]:
        with self._lock:
            return list(self._items_by_namespace.get(namespace, ()))


class QdrantVectorStore:
    backend_name = "qdrant_vector_store"
    _SAFE_COLLECTION_RE = re.compile(r"[^A-Za-z0-9_-]+")

    def __init__(
        self,
        *,
        url: str | None = None,
        path: str | Path = ".cache/qdrant",
        collection_name: str = "rapidcanvas_context",
        collection_scope: str = "default",
        client: Any | None = None,
    ) -> None:
        self._collection_prefix = self._safe_collection_part(collection_name)
        self._collection_scope = self._safe_collection_part(collection_scope)
        default_collection = self._collection_name(0)
        self._active_collection: ContextVar[str] = ContextVar(
            f"qdrant_collection:{id(self)}",
            default=default_collection,
        )
        self._thread = local()
        self._thread.collection_name = default_collection
        if client is not None:
            self._client = client
        else:
            qdrant_client = importlib.import_module("qdrant_client")
            client_kwargs = {"url": url} if url else {"path": str(path)}
            self._client = qdrant_client.QdrantClient(**client_kwargs)

    def ensure_collection(self, vector_size: int) -> None:
        models = importlib.import_module("qdrant_client.models")
        collection_name = self._collection_name(vector_size)
        self._set_active_collection(collection_name)
        if self._collection_exists(collection_name):
            return
        try:
            self._client.create_collection(
                collection_name=collection_name,
                vectors_config=models.VectorParams(
                    size=vector_size, distance=models.Distance.COSINE
                ),
            )
        except Exception:
            if not self._collection_exists(collection_name):
                raise

    def upsert(
        self,
        namespace: str,
        chunks: Sequence[DocumentChunk],
        embeddings: Sequence[list[float]],
    ) -> None:
        models = importlib.import_module("qdrant_client.models")
        points = [
            models.PointStruct(
                id=qdrant_point_id(chunk, namespace),
                vector=embedding,
                payload=qdrant_payload(chunk, namespace),
            )
            for chunk, embedding in zip(chunks, embeddings, strict=True)
        ]
        self._client.upsert(collection_name=self._current_collection(), points=points)

    def query(
        self,
        namespace: str,
        embedding: list[float],
        limit: int,
    ) -> list[VectorSearchResult]:
        limit_value = safe_limit(limit)
        if limit_value == 0:
            return []
        query_filter = self._namespace_filter(namespace)
        if hasattr(self._client, "query_points"):
            response = self._client.query_points(
                collection_name=self._current_collection(),
                query=embedding,
                limit=limit_value,
                query_filter=query_filter,
            )
            points = response.points
        else:
            points = self._client.search(
                collection_name=self._current_collection(),
                query_vector=embedding,
                limit=limit_value,
                query_filter=query_filter,
            )
        return [_point_to_result(point) for point in points]

    def clear_namespace(self, namespace: str) -> None:
        models = importlib.import_module("qdrant_client.models")
        selector = models.FilterSelector(filter=self._namespace_filter(namespace))
        self._client.delete(
            collection_name=self._current_collection(),
            points_selector=selector,
            wait=True,
        )

    def _set_active_collection(self, collection_name: str) -> None:
        self._active_collection.set(collection_name)
        self._thread.collection_name = collection_name

    def _current_collection(self) -> str:
        return self._active_collection.get() or self._thread.collection_name

    def _collection_exists(self, collection_name: str) -> bool:
        collection_exists = getattr(self._client, "collection_exists", None)
        if callable(collection_exists):
            try:
                return bool(collection_exists(collection_name=collection_name))
            except TypeError:
                return bool(collection_exists(collection_name))
        try:
            self._client.get_collection(collection_name=collection_name)
            return True
        except Exception:
            return False

    def _namespace_filter(self, namespace: str) -> Any:
        models = importlib.import_module("qdrant_client.models")
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="namespace",
                    match=models.MatchValue(value=namespace),
                )
            ]
        )

    def _collection_name(self, vector_size: int) -> str:
        size_part = self._vector_size_part(vector_size)
        return f"{self._collection_prefix}_{self._collection_scope}_{size_part}"

    @classmethod
    def _safe_collection_part(cls, value: str) -> str:
        normalized = cls._SAFE_COLLECTION_RE.sub("_", value.strip())[:48].strip("_")
        return normalized or "default"

    @staticmethod
    def _vector_size_part(vector_size: object) -> int:
        try:
            value = int(cast(Any, vector_size))
        except Exception:
            return 0
        return value if value > 0 else 0


def _point_to_result(point: Any) -> VectorSearchResult:
    payload = payload_mapping(getattr(point, "payload", {}) or {})
    chunk = DocumentChunk(
        id=boundary_text(payload_value(payload, "chunk_id"), "chunk_id_text_failed"),
        document_id=boundary_text(payload_value(payload, "document_id"), "document_id_text_failed"),
        source_id=boundary_text(payload_value(payload, "source_id"), "source_id_text_failed"),
        text=boundary_text(payload_value(payload, "text"), "chunk_text_failed"),
        metadata=metadata_mapping(payload_value(payload, "metadata", None)),
    )
    return VectorSearchResult(chunk=chunk, score=public_score(getattr(point, "score", 0.0)))
