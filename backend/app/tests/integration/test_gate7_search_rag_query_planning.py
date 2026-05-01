from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.agent.program import BlueskyExplainer
from app.agent.query_planning import adaptive_runtime_queries, bounded_queries, runtime_queries
from app.agent.runner import HeuristicSignatureRunner
from app.agent.service import AgentExplainerService
from app.ml import diagnostics as d
from app.schemas.api import ExplainRequest
from app.schemas.domain import ContextDocument, Evidence, ExternalLink, PostContext

GATE7_URL = "https://bsky.app/profile/example.com/post/3gate7runtime"


class ContextFetcher:
    def fetch_context(self, url: str) -> PostContext:
        return PostContext(
            url=url,
            at_uri="at://did:plc:gate7/app.bsky.feed.post/3runtime",
            author="example.com",
            text="Gate 7 runtime search needs context.",
            created_at=datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
            parent_texts=["Parent reply asks why this rollout matters."],
            quoted_texts=["Quoted launch claim mentions the original benchmark."],
            links=["https://example.org/runtime-background"],
            external_links=[
                ExternalLink(
                    url="https://example.net/analysis",
                    title="Linked runtime analysis",
                    description="Explains the source evidence.",
                )
            ],
        )


class ManyQueryRunner(HeuristicSignatureRunner):
    def generate_queries(self, post: PostContext, category: str) -> list[str]:
        del post, category
        return ["planned base", "planned second", "planned third", "planned fourth"]


class QueryCapturingRetriever:
    warnings = ()

    def __init__(self) -> None:
        self.queries: list[str] = []

    def retrieve(
        self,
        post: PostContext,
        queries: Sequence[str] = (),
    ) -> tuple[Sequence[Evidence], Sequence[ContextDocument]]:
        del post, queries
        raise AssertionError("Agent service should prefer full retrieval result")

    def retrieve_result(self, post: PostContext, queries: Sequence[str] = ()) -> d.RetrievalResult:
        del post
        self.queries = list(queries)
        documents = [
            ContextDocument(
                id=f"D{index}",
                source_type="web",
                title=f"Query planning source {index}",
                url=f"https://example.com/query-planning-{index}",
                text=f"Query planning evidence {index} supports the runtime explanation.",
                metadata={},
            )
            for index in range(1, 4)
        ]
        evidence = [
            Evidence(
                id=f"E{index}",
                document_id=f"D{index}",
                text=f"Query planning evidence {index} supports the runtime explanation.",
                score=0.9,
                source_id=f"D{index}",
            )
            for index in range(1, 4)
        ]
        return d.make_retrieval_result(
            documents=documents,
            evidence=evidence,
            queries=list(queries),
            prompt_flags=[],
            warnings=[],
            private_url_blocks=[],
        )


def test_gate7_runtime_queries_merge_plan_thread_and_link_context_under_cap() -> None:
    retriever = QueryCapturingRetriever()
    service = AgentExplainerService(
        fetcher=ContextFetcher(),
        retriever=retriever,
        program=BlueskyExplainer(runner=ManyQueryRunner()),
    )

    response = service.explain(ExplainRequest(post_url=GATE7_URL, provider="openai"))

    assert len(retriever.queries) == 3
    assert retriever.queries[0] == "planned base"
    assert any("Quoted launch claim" in query for query in retriever.queries)
    assert any("Linked runtime analysis" in query for query in retriever.queries)
    assert response.trace.queries == retriever.queries


def test_gate7_runtime_queries_skip_private_link_hints_before_search() -> None:
    post = PostContext(
        url=GATE7_URL,
        at_uri="at://did:plc:gate7/app.bsky.feed.post/3runtime",
        author="example.com",
        text="Gate 7 runtime uses public context.",
        created_at=datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
        links=[
            "http://127.0.0.1/admin",
            "http://localhost/private",
            "https://127.0.0.1.nip.io/secret",
            "https://user:token@news.example/credentialed",
            "https://public.example/articles",
        ],
        external_links=[
            ExternalLink(
                url="http://127.0.0.1/admin",
                title="Local admin",
                description="Private service description",
            ),
            ExternalLink(
                url="https://user:token@news.example/credentialed",
                title="Credentialed mirror",
                description="Credential-bearing source description",
            ),
            ExternalLink(
                url="https://news.example/story",
                title="Public context",
                description="Reviewed source description.",
            ),
        ],
    )

    queries = runtime_queries(post, "link_context", ["planned base"])
    query_text = " ".join(queries).lower()

    assert len(queries) <= 3
    assert "planned base" in queries
    assert "public context" in query_text
    assert "news.example" in query_text
    assert "127.0.0.1" not in query_text
    assert "localhost" not in query_text
    assert "local admin" not in query_text
    assert "private service" not in query_text
    assert "user:token" not in query_text
    assert "credentialed mirror" not in query_text


def test_gate7_bounded_queries_strip_unsafe_planned_query_tokens() -> None:
    queries = bounded_queries(
        [
            (
                "planned http://127.0.0.1/admin localhost "
                "https://user:token@news.example/secret "
                "user:token@news.example/secret sk-testsecret context"
            ),
            "safe public context",
        ]
    )
    query_text = " ".join(queries).lower()

    assert queries[0] == "planned context"
    assert queries[1] == "safe public context"
    assert "127.0.0.1" not in query_text
    assert "localhost" not in query_text
    assert "user:token" not in query_text
    assert "sk-testsecret" not in query_text


def test_gate7_adaptive_queries_return_only_one_safe_new_query() -> None:
    post = PostContext(
        url=GATE7_URL,
        at_uri="at://did:plc:gate7/app.bsky.feed.post/3runtime",
        author="example.com",
        text="Gate 7 adaptive retrieval should stay bounded.",
        created_at=datetime(2026, 5, 1, 13, 30, tzinfo=UTC),
    )

    queries = adaptive_runtime_queries(
        post,
        "runtime",
        [
            "example.com runtime background context",
            "Gate 7 adaptive retrieval should stay background context",
        ],
    )

    assert len(queries) == 1
    assert queries[0] == "example.com Bluesky post context"
