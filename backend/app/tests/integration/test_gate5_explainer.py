from __future__ import annotations

import json
from collections.abc import Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

from app.agent.program import BlueskyExplainer
from app.agent.service import AgentExplainerService
from app.agent.sources import POST_SOURCE_ID
from app.schemas.api import ExplainRequest, ExplainResponse
from app.schemas.domain import PostContext

FIXTURE_PATH = (
    Path(__file__).parents[1]
    / "fixtures"
    / "gate5_explainer"
    / "dev_b_retrieval_result.json"
)
C2_RETRIEVAL_FIXTURE_PATH = (
    Path(__file__).parents[1] / "fixtures" / "gate5_retrieval" / "c2_retrieval_result.json"
)


class FixtureFetcher:
    def __init__(self, post: PostContext) -> None:
        self._post = post

    def fetch_context(self, url: str) -> PostContext:
        assert url == self._post.url
        return self._post


class DevBShapedRetriever:
    warnings = ("retriever_property_warning",)

    def __init__(self, payload: dict[str, Any], *, expected_author: str = "example.com") -> None:
        self._payload = payload
        self._expected_author = expected_author
        self.seen_queries: list[str] = []

    def retrieve(self, post: PostContext, queries: Sequence[str] = ()) -> dict[str, Any]:
        assert post.author == self._expected_author
        self.seen_queries = list(queries)
        return self._payload


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


def test_gate5_consumes_dev_b_c2_retrieval_contract() -> None:
    payload = json.loads(C2_RETRIEVAL_FIXTURE_PATH.read_text())
    post = _post_from_dev_b_c2_payload(payload)
    retriever = DevBShapedRetriever(
        _without_guardrail_diagnostics(payload),
        expected_author="science.example",
    )
    service = AgentExplainerService(
        fetcher=FixtureFetcher(post),
        retriever=retriever,
        program=BlueskyExplainer(),
    )

    response = service.explain(ExplainRequest(post_url=post.url, provider="openai"))

    assert isinstance(ExplainResponse.model_validate(response.model_dump()), ExplainResponse)
    response_source_ids = {source.id for source in response.sources}
    dev_b_evidence_source_ids = {item["source_id"] for item in payload["evidence"]}
    cited_source_ids = {
        source_id for bullet in response.bullets for source_id in bullet.source_ids
    }
    assert dev_b_evidence_source_ids <= response_source_ids
    assert cited_source_ids <= response_source_ids
    assert cited_source_ids & dev_b_evidence_source_ids
    assert response.trace.fallback_mode == "none"

    flagged_retriever = DevBShapedRetriever(payload, expected_author="science.example")
    flagged_service = AgentExplainerService(
        fetcher=FixtureFetcher(post),
        retriever=flagged_retriever,
        program=BlueskyExplainer(),
    )
    flagged_response = flagged_service.explain(ExplainRequest(post_url=post.url, provider="openai"))

    assert "fixture_post_context" in flagged_response.trace.warnings
    assert any(
        "blocked_link:http://127.0.0.1/admin" in item
        for item in flagged_response.trace.warnings
    )
    assert "prompt_injection_risk" in flagged_response.trace.guardrail_flags
    assert "private_url_blocked" in flagged_response.trace.guardrail_flags
    assert flagged_response.trace.fallback_mode in {"partial", "safe_summary", "abstain"}
    assert flagged_response.trace.trust_score < response.trace.trust_score


def _post_from_dev_b_c2_payload(payload: dict[str, Any]) -> PostContext:
    target = next(item for item in payload["documents"] if item["id"] == "POST-target")
    metadata = target["metadata"]
    return PostContext.model_validate(
        {
            "url": target["url"],
            "at_uri": metadata["at_uri"],
            "author": metadata["author"],
            "text": target["text"],
            "created_at": metadata["created_at"],
        }
    )


def _without_guardrail_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    clean = deepcopy(payload)
    clean["warnings"] = []
    clean["guardrail_flags"] = []
    clean["private_url_blocks"] = []
    diagnostics = clean["diagnostics"]
    diagnostics["prompt_injection_flags"] = []
    diagnostics["warnings"] = []
    diagnostics["private_url_blocks"] = []
    return clean
