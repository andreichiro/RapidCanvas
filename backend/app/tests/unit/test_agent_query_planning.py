from __future__ import annotations

from datetime import UTC, datetime

from app.agent.query_planning import runtime_queries
from app.schemas.domain import ImageRef, PostContext


def test_runtime_queries_include_image_alt_text_for_visual_context() -> None:
    post = PostContext(
        url="https://bsky.app/profile/jay.bsky.team/post/3mjko6vtdps2b",
        at_uri="at://did:plc:example/app.bsky.feed.post/3mjko6vtdps2b",
        author="jay.bsky.team",
        text="amazon prime william morris vibes",
        created_at=datetime(2026, 4, 11, tzinfo=UTC),
        images=[
            ImageRef(
                url="https://cdn.bsky.app/img/feed_fullsize/plain/did/img",
                alt_text="tree of life art",
            )
        ],
    )

    queries = runtime_queries(post, "image_context", ["amazon prime william morris vibes"])

    assert any("tree of life art" in query for query in queries)
    assert len(queries) <= 3
