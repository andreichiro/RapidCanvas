from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.program import BlueskyExplainer
from app.agent.runner import HeuristicSignatureRunner
from app.agent.service import AgentExplainerService
from app.ml import diagnostics as d
from app.schemas.api import ExplainRequest
from app.schemas.domain import ContextDocument, Evidence, PostContext

GATE7_URL = "https://bsky.app/profile/example.com/post/3gate7runtime"


class StaticFetcher:
    def fetch_context(self, url: str) -> PostContext:
        return PostContext(
            url=url,
            at_uri="at://did:plc:gate7/app.bsky.feed.post/3runtime",
            author="example.com",
            text="Gate 7 diagnostic trace check.",
            created_at=datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        )


class UnorderedEvidenceRetriever:
    warnings = ()

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] = (),
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del post, queries
        raise AssertionError("Agent service should prefer ranked full retrieval result")

    def retrieve_result(self, post: PostContext, queries: Sequence[str] = ()) -> d.RetrievalResult:
        del post, queries
        documents = [
            ContextDocument(
                id=document_id,
                source_type="web",
                title=f"Ranking source {document_id}",
                url=f"https://example.com/{document_id}",
                text=f"{document_id} evidence for source ordering.",
                metadata={},
            )
            for document_id in ("D-low", "D-high", "D-mid")
        ]
        evidence = [
            Evidence(
                id="E-low",
                document_id="D-low",
                text="Low scoring evidence.",
                score=0.25,
                source_id="D-low",
            ),
            Evidence(
                id="E-high",
                document_id="D-high",
                text="High scoring evidence.",
                score=0.98,
                source_id="D-high",
            ),
            Evidence(
                id="E-mid",
                document_id="D-mid",
                text="Medium scoring evidence.",
                score=0.67,
                source_id="D-mid",
            ),
        ]
        return d.make_retrieval_result(
            documents=documents,
            evidence=evidence,
            queries=["ranking query"],
            prompt_flags=[],
            warnings=[],
            private_url_blocks=[],
        )


def test_gate7_sources_follow_ranked_evidence_order() -> None:
    service = AgentExplainerService(
        fetcher=StaticFetcher(),
        retriever=UnorderedEvidenceRetriever(),
        program=BlueskyExplainer(runner=HeuristicSignatureRunner()),
    )

    response = service.explain(ExplainRequest(post_url=GATE7_URL, provider="openai"))

    assert [source.id for source in response.sources[:4]] == [
        "S-post",
        "D-high",
        "D-mid",
        "D-low",
    ]
    assert response.bullets[0].source_ids == ["D-high"]
