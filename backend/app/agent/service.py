"""Route-compatible service wrapper for the Dev C agent program."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from app.agent.program import BlueskyExplainer
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext


@dataclass(frozen=True)
class StaticEvidenceRetriever:
    """Test helper retriever for FastAPI service integration tests."""

    evidence: Sequence[Evidence] = field(default_factory=list)
    documents: Sequence[ContextDocument] = field(default_factory=list)
    warnings: Sequence[str] = field(default_factory=list)

    def retrieve(self, post: PostContext) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del post
        return self.evidence, self.documents


class ThreadContextEvidenceRetriever:
    """Temporary Dev C retriever using normalized Bluesky thread context as evidence."""

    warnings: Sequence[str] = (
        "search_rag_not_connected_using_thread_context_evidence",
        "dev_c_api_path_uses_agent_guardrails",
    )

    def retrieve(self, post: PostContext) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        documents = self._documents(post)
        evidence = [
            Evidence(
                id=f"E{index}",
                document_id=document.id,
                text=document.text,
                score=float(document.metadata.get("score", 0.55)),
                source_id=f"S{index}",
            )
            for index, document in enumerate(documents, start=1)
            if document.text.strip()
        ]
        return evidence, documents

    def _documents(self, post: PostContext) -> list[ContextDocument]:
        documents = [
            ContextDocument(
                id="D1",
                source_type="thread",
                title=f"Bluesky post by {post.author}",
                url=post.url,
                text=post.text or "The fetched post has no text.",
                metadata={"score": 0.72},
            )
        ]
        documents.extend(
            ContextDocument(
                id=f"DP{index}",
                source_type="thread",
                title="Bluesky parent context",
                url=post.url,
                text=text,
                metadata={"score": 0.66},
            )
            for index, text in enumerate(post.parent_texts, start=1)
        )
        documents.extend(
            ContextDocument(
                id=f"DQ{index}",
                source_type="thread",
                title="Bluesky quoted context",
                url=post.url,
                text=text,
                metadata={"score": 0.62},
            )
            for index, text in enumerate(post.quoted_texts, start=1)
        )
        documents.extend(
            ContextDocument(
                id=f"DI{index}",
                source_type="image",
                title="Bluesky image alt text",
                url=image.url,
                text=image.alt_text or "Image was present but had no alt text.",
                metadata={"score": 0.5},
            )
            for index, image in enumerate(post.images, start=1)
        )
        return documents


class PostContextFetcher(Protocol):
    """Protocol for Dev A's Bluesky client without importing the client module."""

    def fetch_context(self, url: str) -> PostContext:
        """Fetch a normalized public post context."""


class EvidenceRetriever(Protocol):
    """Protocol for Dev B retrieval without coupling to client modules."""

    @property
    def warnings(self) -> Sequence[str]:
        """Non-fatal retrieval warnings for trace output."""

    def retrieve(self, post: PostContext) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        """Retrieve evidence and source documents for a post."""


class AgentExplainerService:
    """Route-compatible service that wires fetch, retrieval, and the Dev C program."""

    def __init__(
        self,
        *,
        fetcher: PostContextFetcher,
        retriever: EvidenceRetriever,
        program: BlueskyExplainer | None = None,
        extra_warnings: Sequence[str] = (),
    ) -> None:
        self._fetcher = fetcher
        self._retriever = retriever
        self._program = program or BlueskyExplainer()
        self._extra_warnings = extra_warnings

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        post = self._fetcher.fetch_context(request.post_url)
        evidence, documents = self._retriever.retrieve(post)
        warnings = [*getattr(self._retriever, "warnings", ()), *self._extra_warnings]
        return self._program.explain_context(
            post=post,
            evidence=evidence,
            documents=documents,
            request=request,
            warnings=warnings,
        )
