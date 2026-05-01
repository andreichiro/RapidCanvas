from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import cast

from app.ml.vector_payloads import metadata_mapping
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


def test_in_memory_vector_store_treats_dimension_mismatch_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")

    store.recreate_collection(vector_size=2)
    store.upsert([chunk], [[1.0, 0.0]])
    results = store.query([1.0], limit=1)

    assert len(results) == 1
    assert results[0].chunk.id == "C1"
    assert results[0].score == 0.0


def test_in_memory_vector_store_treats_malformed_vectors_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")
    bad_embedding = cast(list[float], ["not-a-number", 0.0])

    store.recreate_collection(vector_size=2)
    store.upsert([chunk], [bad_embedding])
    results = store.query([1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].score == 0.0


def test_in_memory_vector_store_treats_raising_vectors_as_zero_similarity() -> None:
    store = InMemoryVectorStore()
    chunk = DocumentChunk(id="C1", document_id="D1", source_id="D1", text="mars rover")
    bad_embedding = cast(list[float], [BadFloat(), 0.0])

    store.recreate_collection(vector_size=2)
    store.upsert([chunk], [bad_embedding])
    results = store.query([1.0, 0.0], limit=1)

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

    results = QdrantVectorStore(client=MalformedClient()).query([1.0, 0.0], limit=1)

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

    results = QdrantVectorStore(client=MalformedClient()).query([1.0, 0.0], limit=1)

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

    results = QdrantVectorStore(client=MalformedClient()).query([1.0, 0.0], limit=1)

    assert len(results) == 1
    assert results[0].score == 0.0


def test_metadata_mapping_degrades_bad_mapping_iteration() -> None:
    assert metadata_mapping(BadMapping()) == {
        "metadata_iter_failed": "metadata_iter_failed:RuntimeError"
    }
