from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime
from threading import Event, Thread
from typing import Any, cast

import pytest

from app.agent.service import EvidenceRetriever
from app.ml import diagnostics as d
from app.ml.embeddings import DeterministicHashEmbeddingProvider
from app.ml.rerankers import SimilarityReranker
from app.ml.retrieval_adapter import RetrievalEvidenceRetriever
from app.ml.retrieval_service import RetrievalService, RetrievalSettings
from app.ml.vector_store import InMemoryVectorStore, RagService
from app.schemas.domain import PostContext


class FailingRetrievalService:
    async def retrieve(
        self,
        post: PostContext,
        queries: object = None,
        settings: object = None,
    ) -> object:
        del post, queries, settings
        raise RuntimeError("boom")


class WarningRetrievalService:
    async def retrieve(
        self,
        post: PostContext,
        queries: object = None,
        settings: object = None,
    ) -> d.RetrievalResult:
        del queries, settings
        return d.make_retrieval_result(
            documents=[],
            evidence=[],
            queries=[],
            prompt_flags=[],
            warnings=[f"retrieval_warning:{post.author}"],
            private_url_blocks=[],
        )


class AsyncWarningRetrievalService:
    def __init__(self) -> None:
        self.alpha_started = asyncio.Event()
        self.release_alpha = asyncio.Event()

    async def retrieve(
        self,
        post: PostContext,
        queries: object = None,
        settings: object = None,
    ) -> d.RetrievalResult:
        del queries, settings
        if post.author == "alpha.example":
            self.alpha_started.set()
            await self.release_alpha.wait()
        else:
            await self.alpha_started.wait()
            self.release_alpha.set()
        return d.make_retrieval_result(
            documents=[],
            evidence=[],
            queries=[],
            prompt_flags=[],
            warnings=[f"retrieval_warning:{post.author}"],
            private_url_blocks=[],
        )


def post_context() -> PostContext:
    return PostContext(
        url="https://bsky.app/profile/science.example/post/3kadapter",
        at_uri="at://did:plc:science/app.bsky.feed.post/3kadapter",
        author="science.example",
        text="Mars rover evidence asks whether hydrated minerals imply past water.",
        created_at=datetime(2026, 4, 30, 12, 0, tzinfo=UTC),
    )


def retrieval_service() -> RetrievalService:
    return RetrievalService(
        rag_service=RagService(
            embedding_provider=DeterministicHashEmbeddingProvider(),
            vector_store=InMemoryVectorStore(),
            reranker=SimilarityReranker(),
        ),
        search_providers=[],
        settings=RetrievalSettings(include_linked_pages=False, include_search=False),
    )


def test_retrieval_adapter_matches_agent_evidence_retriever_contract() -> None:
    retriever = RetrievalEvidenceRetriever(retrieval_service(), queries=["mars rover water"])
    protocol_retriever: EvidenceRetriever = retriever

    result = protocol_retriever.retrieve(post_context(), queries=["mars rover water"])
    assert isinstance(result, tuple)
    evidence, documents = result

    assert evidence
    assert documents
    assert retriever.last_result is not None
    assert retriever.last_result.evidence == list(evidence)
    assert retriever.last_result.documents == list(documents)
    assert retriever.warnings == tuple(retriever.last_result.warnings)
    assert retriever.guardrail_flags == tuple(retriever.last_result.guardrail_flags)
    assert retriever.diagnostics == retriever.last_result.diagnostics


@pytest.mark.asyncio
async def test_retrieval_adapter_exposes_async_full_c2_result() -> None:
    retriever = RetrievalEvidenceRetriever(retrieval_service(), queries=["mars rover water"])

    result = await retriever.retrieve_result_async(post_context())

    assert result.evidence
    assert result.documents
    assert retriever.last_result == result
    assert retriever.warnings == tuple(result.warnings)


@pytest.mark.asyncio
async def test_retrieval_adapter_sync_bridge_works_inside_running_loop() -> None:
    retriever = RetrievalEvidenceRetriever(retrieval_service(), queries=["mars rover water"])

    evidence, documents = retriever.retrieve(post_context())

    assert evidence
    assert documents


def test_retrieval_adapter_fails_closed_for_unexpected_service_errors() -> None:
    retriever = RetrievalEvidenceRetriever(cast(Any, FailingRetrievalService()))

    evidence, documents = retriever.retrieve(post_context())

    assert evidence == []
    assert documents == []
    assert "retrieval_adapter_failed:RuntimeError" in retriever.warnings
    assert "retrieval_unavailable" in retriever.guardrail_flags


def test_retrieval_adapter_keeps_warning_state_isolated_between_threads() -> None:
    retriever = RetrievalEvidenceRetriever(cast(Any, WarningRetrievalService()))
    alpha_retrieved = Event()
    beta_done = Event()
    results: dict[str, Sequence[str]] = {}

    def run_alpha() -> None:
        retriever.retrieve(post_context().model_copy(update={"author": "alpha.example"}))
        alpha_retrieved.set()
        assert beta_done.wait(timeout=5)
        results["alpha"] = retriever.warnings

    def run_beta() -> None:
        assert alpha_retrieved.wait(timeout=5)
        retriever.retrieve(post_context().model_copy(update={"author": "beta.example"}))
        results["beta"] = retriever.warnings
        beta_done.set()

    alpha = Thread(target=run_alpha)
    beta = Thread(target=run_beta)
    alpha.start()
    beta.start()
    alpha.join(timeout=5)
    beta.join(timeout=5)

    assert results["alpha"] == ("retrieval_warning:alpha.example",)
    assert results["beta"] == ("retrieval_warning:beta.example",)


@pytest.mark.asyncio
async def test_retrieval_adapter_keeps_warning_state_isolated_between_async_tasks() -> None:
    retriever = RetrievalEvidenceRetriever(cast(Any, AsyncWarningRetrievalService()))

    async def run(author: str) -> Sequence[str]:
        await retriever.retrieve_result_async(post_context().model_copy(update={"author": author}))
        return retriever.warnings

    alpha, beta = await asyncio.gather(run("alpha.example"), run("beta.example"))

    assert alpha == ("retrieval_warning:alpha.example",)
    assert beta == ("retrieval_warning:beta.example",)
