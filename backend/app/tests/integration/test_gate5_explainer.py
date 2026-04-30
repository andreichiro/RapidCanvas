from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from app.agent.program import BlueskyExplainer
from app.agent.service import AgentExplainerService
from app.agent.sources import POST_SOURCE_ID
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import ContextDocument, Evidence, PostContext

FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "gate5_explainer"
    / "dev_b_retrieval_result.json"
)


class FixtureFetcher:
    def __init__(self, post: PostContext) -> None:
        self._post = post

    def fetch_context(self, url: str) -> PostContext:
        assert url == self._post.url
        return self._post


class DevBShapedRetriever:
    warnings = ("retriever_property_warning",)

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.seen_queries: list[str] = []

    def retrieve(self, post: PostContext, queries: Sequence[str] = ()) -> dict[str, Any]:
        assert post.author == "example.com"
        self.seen_queries = list(queries)
        return {
            **self._payload,
            "context_documents": [
                ContextDocument.model_validate(item)
                for item in self._payload["context_documents"]
            ],
            "evidence": [Evidence.model_validate(item) for item in self._payload["evidence"]],
        }


def test_gate5_explainer_consumes_dev_b_shaped_evidence_and_returns_schema() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    post = PostContext.model_validate(fixture["post"])
    retriever = DevBShapedRetriever(fixture["retrieval_result"])
    service = AgentExplainerService(
        fetcher=FixtureFetcher(post),
        retriever=retriever,
        program=BlueskyExplainer(),
    )
    request = ExplainRequest(post_url=post.url, provider="openai")

    response = service.explain(request)

    assert isinstance(ExplainResponse.model_validate(response.model_dump()), ExplainResponse)
    assert retriever.seen_queries
    assert 3 <= len(response.bullets) <= 5
    assert response.trace.fallback_mode == "none"
    assert response.trace.queries == retriever.seen_queries
    assert "bsky_parent_context_loaded" in response.trace.warnings
    assert "dev_b_fixture_retrieval_result" in response.trace.warnings
    assert "retrieval_top_k:3" in response.trace.warnings
    assert {source.id for source in response.sources} == {
        POST_SOURCE_ID,
        "S-web-launch",
        "S-web-pricing",
        "S-bsky-discussion",
    }
    assert all(
        source_id in {source.id for source in response.sources}
        for bullet in response.bullets
        for source_id in bullet.source_ids
    )


def test_gate5_retrieval_diagnostics_influence_trust_and_fallback() -> None:
    fixture = json.loads(FIXTURE_PATH.read_text())
    fixture["retrieval_result"]["diagnostics"]["prompt_injection_flags"] = [
        "prompt_injection_risk",
        "source_safety_private_url_blocked",
    ]
    fixture["retrieval_result"]["diagnostics"]["warnings"].append(
        "prompt_injection_risk:D-web-launch"
    )
    post = PostContext.model_validate(fixture["post"])
    retriever = DevBShapedRetriever(fixture["retrieval_result"])
    service = AgentExplainerService(
        fetcher=FixtureFetcher(post),
        retriever=retriever,
        program=BlueskyExplainer(),
    )

    response = service.explain(ExplainRequest(post_url=post.url, provider="openai"))

    assert "prompt_injection_risk" in response.trace.guardrail_flags
    assert "source_safety_private_url_blocked" in response.trace.guardrail_flags
    assert response.trace.fallback_mode in {"partial", "safe_summary", "abstain"}
