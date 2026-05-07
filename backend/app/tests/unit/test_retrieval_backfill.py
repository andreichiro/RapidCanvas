from __future__ import annotations

from app.ml.retrieval_backfill import with_quality_backfill
from app.schemas.domain import ContextDocument, Evidence


def test_quality_backfill_keeps_citation_eligible_image_alt_evidence() -> None:
    post_evidence = Evidence(
        id="E1",
        document_id="POST-target",
        source_id="POST-target",
        text="amazon prime william morris vibes",
        score=0.72,
    )
    image = ContextDocument(
        id="POST-image-1",
        source_type="image",
        title="Bluesky image alt text",
        url="https://cdn.bsky.app/img/feed_fullsize/plain/did/img",
        text="tree of life art",
        metadata={
            "citation_eligible": True,
            "citation_role": "primary",
            "source_quality_score": 0.52,
            "image_evidence_available": True,
        },
    )

    evidence = with_quality_backfill(
        [
            ContextDocument(
                id="POST-target",
                source_type="thread",
                title="Visible Bluesky post",
                url="https://bsky.app/profile/jay.bsky.team/post/3mjko6vtdps2b",
                text="amazon prime william morris vibes",
                metadata={"citation_eligible": True, "citation_role": "primary"},
            ),
            image,
        ],
        [post_evidence],
        limit=3,
    )

    assert {item.document_id for item in evidence} == {"POST-target", "POST-image-1"}


def test_quality_backfill_replaces_low_value_search_evidence_with_image_alt() -> None:
    low_search = [
        Evidence(
            id=f"E{index}",
            document_id=f"WEB-{index}",
            source_id=f"WEB-{index}",
            text="Thin shopping search result.",
            score=0.2 + index / 100,
        )
        for index in range(1, 7)
    ]
    image = ContextDocument(
        id="POST-image-1",
        source_type="image",
        title="Bluesky image alt text",
        url="https://cdn.bsky.app/img/feed_fullsize/plain/did/img",
        text="tree of life art",
        metadata={
            "citation_eligible": True,
            "citation_role": "primary",
            "source_quality_score": 0.72,
            "image_evidence_available": True,
        },
    )

    evidence = with_quality_backfill([image], low_search, limit=6)

    assert "POST-image-1" in {item.document_id for item in evidence}
    assert len(evidence) == 6
