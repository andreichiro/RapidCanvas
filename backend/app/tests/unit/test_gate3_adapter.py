from __future__ import annotations

from datetime import UTC, datetime

from app.agent.dev_adapter import Gate3Explainer
from app.schemas.api import ExplainRequest
from app.schemas.domain import PostContext


class FakeBlueskyClient:
    def fetch_context(self, url: str) -> PostContext:
        return PostContext(
            url=url,
            at_uri="at://did:plc:example/app.bsky.feed.post/3abcxyz",
            author="example.com",
            text="This is a fetched Bluesky post.",
            created_at=datetime(2026, 4, 29, tzinfo=UTC),
            parent_texts=["A parent post"],
            quoted_texts=[],
            links=[],
            images=[],
        )


def test_gate3_adapter_returns_cited_safe_summary_with_trace_flags() -> None:
    explainer = Gate3Explainer(bluesky_client=FakeBlueskyClient())
    request = ExplainRequest(
        post_url="https://bsky.app/profile/example.com/post/3abcxyz",
        provider="openai",
    )

    response = explainer.explain(request)

    assert len(response.bullets) == 3
    assert all(bullet.source_ids for bullet in response.bullets)
    assert response.sources[0].id == "S1"
    assert response.trace.fallback_mode == "safe_summary"
    assert response.trace.adapter_mode == "deterministic_fallback"
    assert "deterministic_fallback_search_rag" in response.trace.guardrail_flags
    assert "limited_context_fallback" in response.trace.guardrail_flags
    assert "real_bluesky_fetch_enabled" in response.trace.warnings
    assert any(
        "limited to fetched Bluesky context" in note for note in response.trace.adapter_notes
    )
