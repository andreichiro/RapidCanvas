from __future__ import annotations

from datetime import UTC, datetime

from app.ml.source_quality import citation_eligible, score_document_quality
from app.schemas.domain import ContextDocument, ImageRef, PostContext


def test_image_alt_text_matches_post_image_context_for_quality() -> None:
    post = PostContext(
        url="https://bsky.app/profile/jay.bsky.team/post/3mjko6vtdps2b",
        at_uri="at://did:plc:jay/app.bsky.feed.post/3mjko6vtdps2b",
        author="jay.bsky.team",
        text="amazon prime william morris vibes",
        created_at=datetime(2026, 4, 11, tzinfo=UTC),
        images=[
            ImageRef(
                url="https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:x/img",
                alt_text="tree of life art",
            )
        ],
    )
    image = ContextDocument(
        id="IMG-ALT",
        source_type="image",
        title="Bluesky image alt text",
        url="https://cdn.bsky.app/img/feed_fullsize/plain/did:plc:x/img",
        text="tree of life art",
        metadata={"role": "image_alt_text", "image_index": 1},
    )

    assessment = score_document_quality(
        post,
        "amazon prime william morris vibes tree of life art",
        image,
    )

    assert assessment.score >= 0.5
    assert citation_eligible(image, assessment)
