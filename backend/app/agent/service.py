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
    ) -> None:
        self._fetcher = fetcher
        self._retriever = retriever
        self._program = program or BlueskyExplainer()

    def explain(self, request: ExplainRequest) -> ExplainResponse:
        post = self._fetcher.fetch_context(request.post_url)
        evidence, documents = self._retriever.retrieve(post)
        return self._program.explain_context(
            post=post,
            evidence=evidence,
            documents=documents,
            request=request,
            warnings=getattr(self._retriever, "warnings", ()),
        )

