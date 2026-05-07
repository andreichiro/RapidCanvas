from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ml.source_quality import citation_eligible, score_document_quality
from app.schemas.domain import ContextDocument, PostContext


def _post(**updates: object) -> PostContext:
    values: dict[str, Any] = {
        "url": "https://bsky.app/profile/research.example/post/3abc",
        "at_uri": "at://did:plc:research/app.bsky.feed.post/3abc",
        "author": "research.example",
        "text": "New AT Protocol moderation tooling launched today with Bluesky safety context.",
        "created_at": datetime(2026, 5, 1, tzinfo=UTC),
        "links": ["https://research.example/blog/atproto-moderation-tooling"],
    }
    values.update(updates)
    return PostContext(**values)


def test_robots_disallowed_snippet_is_retrievable_but_not_citation_eligible() -> None:
    post = _post()
    robots_snippet = ContextDocument(
        id="ROBOTS-SNIP",
        source_type="web",
        title="Research Example announces AT Protocol moderation tooling",
        url="https://research.example/blog/atproto-moderation-tooling",
        text=(
            "Research Example announces AT Protocol moderation tooling for Bluesky safety "
            "with moderation labels, launch notes, and implementation details."
        ),
        metadata={
            "provider": "web_search",
            "snippet_only": True,
            "fetch_success": False,
            "fetch_status": "robots_disallowed",
            "fetch_warnings": ["robots_disallowed"],
            "robots_disallowed": True,
            "rank": 1,
        },
    )

    assessment = score_document_quality(post, post.text, robots_snippet)

    assert any("robots_disallowed_fetch" in reason for reason in assessment.reasons)
    assert not citation_eligible(robots_snippet, assessment)
