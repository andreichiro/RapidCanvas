from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest

from app.ml.vector_payloads import metadata_mapping, qdrant_payload, qdrant_point_id
from app.ml.vector_store import DocumentChunk, InMemoryVectorStore, QdrantVectorStore


class BadFloat:
    def __float__(self) -> float:
        raise RuntimeError("bad vector value")


class BadMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise RuntimeError("bad payload")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("bad payload")

    def __len__(self) -> int:
        return 1

    def get(self, key: str, default: object = None) -> object:
        del key, default
        raise RuntimeError("bad payload")


class _EmptyQdrantResponse:
    points: list[object] = []


class _RecordingQdrantClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.upsert_collections: list[str] = []
        self.upsert_payloads: list[dict[str, object]] = []
        self.query_collections: list[str] = []
        self.query_filter: object | None = None
        self.delete_collections: list[str] = []
        self.delete_selector: object | None = None

    def collection_exists(self, collection_name: str) -> bool:
        return collection_name in self.created

    def create_collection(self, **kwargs: object) -> None:
        self.created.append(cast(str, kwargs["collection_name"]))

    def delete_collection(self, **kwargs: object) -> None:
        raise AssertionError(f"collection deletion is forbidden: {kwargs}")

    def upsert(self, **kwargs: object) -> None:
        self.upsert_collections.append(cast(str, kwargs["collection_name"]))
        points = cast(list[object], kwargs["points"])
        self.upsert_payloads.extend(
            cast(dict[str, object], cast(Any, point).payload) for point in points
        )

    def query_points(self, **kwargs: object) -> _EmptyQdrantResponse:
        self.query_collections.append(cast(str, kwargs["collection_name"]))
        self.query_filter = kwargs["query_filter"]
        return _EmptyQdrantResponse()

    def delete(self, **kwargs: object) -> None:
        self.delete_collections.append(cast(str, kwargs["collection_name"]))
        self.delete_selector = kwargs["points_selector"]


def test_in_memory_vector_store_treats_dimension_mismatch_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")

    store.ensure_collection(vector_size=2)
    store.upsert("alpha", [chunk], [[1.0, 0.0]])
    results = store.query("alpha", [1.0], limit=1)

    assert len(results) == 1
    assert results[0].chunk.id == "C1"
    assert results[0].score == 0.0


def test_in_memory_vector_store_treats_malformed_vectors_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")
    bad_embedding = cast(list[float], ["not-a-number", 0.0])

    store.ensure_collection(vector_size=2)
    store.upsert("alpha", [chunk], [bad_embedding])
    results = store.query("alpha", [1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].score == 0.0


def test_in_memory_vector_store_treats_raising_vectors_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")
    bad_embedding = cast(list[float], [BadFloat(), 0.0])

    store.ensure_collection(vector_size=2)
    store.upsert("alpha", [chunk], [bad_embedding])
    results = store.query("alpha", [1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].score == 0.0


def test_qdrant_vector_store_normalizes_malformed_point_payloads() -> None:
    class MalformedPoint:
        score = "not-a-number"
        payload = {
            "chunk_id": "C1",
            "document_id": "D1",
            "source_id": "D1",
            "text": "mars rover",
            "metadata": ["unexpected"],
        }

    class MalformedResponse:
        points = [MalformedPoint()]

    class MalformedClient:
        def query_points(self, **kwargs: object) -> MalformedResponse:
            assert kwargs["limit"] == 1
            return MalformedResponse()

    results = QdrantVectorStore(client=MalformedClient()).query("alpha", [1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].chunk.id == "C1"
    assert results[0].chunk.metadata == {"metadata": ["unexpected"]}
    assert results[0].score == 0.0


def test_qdrant_vector_store_degrades_bad_mapping_payloads() -> None:
    class MalformedPoint:
        score = "0.5"
        payload = BadMapping()

    class MalformedResponse:
        points = [MalformedPoint()]

    class MalformedClient:
        def query_points(self, **kwargs: object) -> MalformedResponse:
            del kwargs
            return MalformedResponse()

    results = QdrantVectorStore(client=MalformedClient()).query("alpha", [1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].chunk.id == ""
    assert results[0].chunk.metadata == {}
    assert results[0].score == 0.5


def test_qdrant_vector_store_degrades_raising_scores() -> None:
    class MalformedPoint:
        score = BadFloat()
        payload = {"chunk_id": "C1"}

    class MalformedResponse:
        points = [MalformedPoint()]

    class MalformedClient:
        def query_points(self, **kwargs: object) -> MalformedResponse:
            del kwargs
            return MalformedResponse()

    results = QdrantVectorStore(client=MalformedClient()).query("alpha", [1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].score == 0.0


def test_metadata_mapping_degrades_bad_mapping_iteration() -> None:
    assert metadata_mapping(BadMapping()) == {
        "metadata_iter_failed": "metadata_iter_failed:RuntimeError"
    }


def test_in_memory_vector_store_isolates_and_clears_namespaces() -> None:
    store = InMemoryVectorStore()
    alpha = DocumentChunk(id="A", document_id="DA", source_id="DA", text="alpha")
    beta = DocumentChunk(id="B", document_id="DB", source_id="DB", text="beta")

    store.ensure_collection(vector_size=2)
    store.upsert("alpha", [alpha], [[1.0, 0.0]])
    store.upsert("beta", [beta], [[0.0, 1.0]])

    assert [result.chunk.id for result in store.query("alpha", [1.0, 0.0], limit=2)] == ["A"]
    assert [result.chunk.id for result in store.query("beta", [0.0, 1.0], limit=2)] == ["B"]

    store.clear_namespace("alpha")

    assert store.query("alpha", [1.0, 0.0], limit=2) == []
    assert [result.chunk.id for result in store.query("beta", [0.0, 1.0], limit=2)] == ["B"]


def test_qdrant_payload_ids_include_namespace() -> None:
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")

    assert qdrant_point_id(chunk, "alpha") != qdrant_point_id(chunk, "beta")
    assert qdrant_payload(chunk, "alpha")["namespace"] == "alpha"


def test_qdrant_vector_store_uses_scoped_collection_and_namespace_filter() -> None:
    pytest.importorskip("qdrant_client")
    client = _RecordingQdrantClient()
    store = QdrantVectorStore(
        client=client,
        collection_scope="text-embedding-3-small",
    )
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")

    store.ensure_collection(vector_size=1536)
    store.ensure_collection(vector_size=1536)
    store.upsert("request-alpha", [chunk], [[1.0, 0.0]])
    assert store.query("request-alpha", [1.0, 0.0], limit=1) == []
    store.clear_namespace("request-alpha")
    store.ensure_collection(vector_size=3)
    store.upsert("request-beta", [chunk], [[1.0, 0.0, 0.0]])

    assert client.created == [
        "rapidcanvas_context_text-embedding-3-small_1536",
        "rapidcanvas_context_text-embedding-3-small_3",
    ]
    assert client.upsert_collections == [
        "rapidcanvas_context_text-embedding-3-small_1536",
        "rapidcanvas_context_text-embedding-3-small_3",
    ]
    assert client.query_collections == ["rapidcanvas_context_text-embedding-3-small_1536"]
    assert client.delete_collections == ["rapidcanvas_context_text-embedding-3-small_1536"]
    assert client.upsert_payloads[0]["namespace"] == "request-alpha"
    assert client.upsert_payloads[1]["namespace"] == "request-beta"
    assert client.query_filter is not None
    assert client.delete_selector is not None
