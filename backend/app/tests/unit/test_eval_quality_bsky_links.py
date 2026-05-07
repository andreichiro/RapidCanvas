from __future__ import annotations

from app.eval.metrics import score_case
from app.tests.unit.test_eval_metrics import make_case, make_fixture


def test_metrics_do_not_mark_high_quality_bsky_link_as_off_topic() -> None:
    fixture = make_fixture(
        bullets=[
            {
                "text": "A starter pack for minor leagues is available in the linked post.",
                "source_ids": ["S1"],
            },
            {
                "text": "The post invites baseball fans to follow minor leagues.",
                "source_ids": ["S2"],
            },
            {"text": "The visible post is the public Bluesky context.", "source_ids": ["S2"]},
        ],
        sources=[
            {
                "id": "S1",
                "title": "@jenramose.online on Bluesky",
                "type": "web",
                "url": "https://bsky.app/profile/jenramose.online/post/3mjvec6mhpk2a",
                "snippet": "Linked Bluesky starter-pack post.",
                "quality_score": 1.0,
            },
            {
                "id": "S2",
                "title": "Visible Bluesky post by bsky.app",
                "type": "thread",
                "url": "https://bsky.app/profile/bsky.app/post/3mjxj5pui322g",
                "snippet": "Who else has baseball fever? follow the minor leagues.",
            },
        ],
    )
    case = make_case(
        category="quote_context",
        expected_source_hints=["starter pack", "minor leagues"],
        expected_context_channels=["thread", "web"],
        provenance="fixture_backed_public",
    )

    score = score_case(case, fixture)

    assert score["off_topic_source_count"] == 0
