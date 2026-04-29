"""Embedding providers and deterministic test embeddings."""

from __future__ import annotations

import hashlib
import importlib
import math
from pathlib import Path
from typing import Protocol

from diskcache import Cache  # type: ignore[import-untyped]

from app.config import Settings, get_settings


class EmbeddingProvider(Protocol):
    """Synchronous embedding provider boundary for retrieval."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector for each input text."""


class OpenAIEmbeddingProvider:
    """OpenAI embedding wrapper with diskcache keyed by model and text hash."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        cache_dir: str | Path = ".cache/embeddings",
    ) -> None:
        self._settings = settings or get_settings()
        self._cache = Cache(str(cache_dir))

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches and cache stable results."""

        if not texts:
            return []
        cached: dict[int, list[float]] = {}
        missing_indexes: list[int] = []
        missing_texts: list[str] = []
        for index, text in enumerate(texts):
            key = self._cache_key(text)
            value = self._cache.get(key)
            if isinstance(value, list):
                cached[index] = [float(item) for item in value]
            else:
                missing_indexes.append(index)
                missing_texts.append(text)

        if missing_texts:
            vectors = self._embed_uncached(missing_texts)
            for index, vector in zip(missing_indexes, vectors, strict=True):
                self._cache.set(self._cache_key(texts[index]), vector)
                cached[index] = vector
        return [cached[index] for index in range(len(texts))]

    def _embed_uncached(self, texts: list[str]) -> list[list[float]]:
        if self._settings.openai_api_key is None:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI embeddings")
        openai = importlib.import_module("openai")
        client = openai.OpenAI(api_key=self._settings.openai_api_key.get_secret_value())
        response = client.embeddings.create(input=texts, model=self._settings.embedding_model)
        return [[float(value) for value in item.embedding] for item in response.data]

    def _cache_key(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self._settings.embedding_model}:{digest}"


class DeterministicHashEmbeddingProvider:
    """Small deterministic embedding provider for tests and offline smoke runs."""

    def __init__(self, dimensions: int = 16) -> None:
        self._dimensions = dimensions

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Map text into normalized hash-bucket vectors."""

        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self._dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = digest[0] % self._dimensions
            vector[index] += 1.0 + digest[1] / 255.0
        return normalize_vector(vector)


def normalize_vector(vector: list[float]) -> list[float]:
    """Return a unit-length copy of a vector, preserving all-zero vectors."""

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


def text_hash(text: str) -> str:
    """Stable SHA-256 digest helper for cache and chunk IDs."""

    return hashlib.sha256(text.encode("utf-8")).hexdigest()
