from __future__ import annotations

from typing import Any

from app.eval.dataset import CachedFixture, EvalCase
from app.eval.metrics import expected_point_recall, score_case


def _fixture(
    *,
    bullets: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    fallback_mode: str = "none",
) -> CachedFixture:
    return CachedFixture(
        prediction={
            "bullets": bullets,
            "sources": sources,
            "trace": {
                "category": "normal",
                "fallback_mode": fallback_mode,
                "adapter_mode": "none",
            },
        },
        retrieved_source_hints=[],
        trace_sequence=["fetch_post", "retrieve", "validate"],
        unsupported_claims=[],
    )


def test_expected_point_recall_counts_conservative_paraphrases_and_context_roles() -> None:
    case = EvalCase(
        id="paraphrase",
        url="https://bsky.app/profile/example.com/post/3paraphrase",
        category="link_context",
        expected_key_points=["AT Protocol", "IETF charter", "linked article"],
        expected_context_channels=["web", "link"],
        expected_source_hints=["AT Protocol"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    prediction = {
        "bullets": [
            {
                "text": (
                    "An Authenticated Transfer Protocol working group has an approved IETF charter."
                ),
                "source_ids": ["S1"],
            },
            {"text": "The summary is supported by the linked source.", "source_ids": ["S1"]},
            {"text": "The article explains the same standards work.", "source_ids": ["S1"]},
        ],
        "sources": [{"id": "S1", "type": "web", "title": "AT Protocol article"}],
        "trace": {"fallback_mode": "none"},
    }

    assert expected_point_recall(case, prediction) == 1.0


def test_linked_article_expected_point_requires_cited_link_or_web_source() -> None:
    case = EvalCase(
        id="linked_false_positive",
        url="https://bsky.app/profile/example.com/post/3linkedfalsepositive",
        category="link_context",
        expected_key_points=["linked article"],
        expected_context_channels=["web", "link"],
        expected_source_hints=["linked source"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    prediction = {
        "bullets": [
            {"text": "This is a safe summary with no linked source.", "source_ids": ["S1"]},
            {"text": "Another summary stays within visible thread context.", "source_ids": ["S1"]},
            {"text": "The answer avoids broader linked-page claims.", "source_ids": ["S1"]},
        ],
        "sources": [{"id": "S1", "type": "thread", "title": "Visible post", "snippet": "post"}],
        "trace": {"fallback_mode": "none"},
    }

    assert expected_point_recall(case, prediction) == 0.0


def test_public_live_quality_pass_requires_live_provider_path() -> None:
    case = EvalCase(
        id="provider_fallback",
        url="https://bsky.app/profile/example.com/post/3providerfallback",
        category="link_context",
        expected_key_points=["linked article", "AT Protocol"],
        expected_context_channels=["web"],
        expected_source_hints=["AT Protocol"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        bullets=[
            {"text": "The linked article is about AT Protocol.", "source_ids": ["S1"]},
            {"text": "AT Protocol context is cited from the source.", "source_ids": ["S1"]},
            {"text": "The answer is source-backed.", "source_ids": ["S1"]},
        ],
        sources=[
            {
                "id": "S1",
                "title": "AT Protocol linked article",
                "type": "web",
                "snippet": "AT Protocol linked article source-backed context.",
            }
        ],
    )
    fixture.prediction["trace"]["adapter_mode"] = "deterministic_fallback"

    score = score_case(case, fixture)

    assert float(score["provider_quality_score"]) < 1.0
    assert score["public_live_quality_pass"] == 0.0


def test_public_live_quality_pass_rejects_missing_provider_execution_trace() -> None:
    case = EvalCase(
        id="missing_provider_trace",
        url="https://bsky.app/profile/example.com/post/3missingprovidertrace",
        category="link_context",
        expected_key_points=["linked article", "AT Protocol"],
        expected_context_channels=["web"],
        expected_source_hints=["AT Protocol"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        bullets=[
            {"text": "The linked article is about AT Protocol.", "source_ids": ["S1"]},
            {"text": "AT Protocol context is cited from the source.", "source_ids": ["S1"]},
            {"text": "The answer is source-backed.", "source_ids": ["S1"]},
        ],
        sources=[
            {
                "id": "S1",
                "title": "AT Protocol linked article",
                "type": "web",
                "snippet": "AT Protocol linked article source-backed context.",
            }
        ],
    )
    fixture.prediction["trace"].pop("adapter_mode", None)

    score = score_case(case, fixture)

    assert score["provider_quality_score"] == 0.0
    assert score["public_live_quality_pass"] == 0.0


def test_public_quality_pass_allows_expected_sparse_context_abstention() -> None:
    case = EvalCase(
        id="sparse",
        url="https://bsky.app/profile/example.com/post/3sparse",
        category="sparse_context",
        expected_key_points=["sparse context", "safe summary", "no broader claim"],
        expected_context_channels=["thread"],
        expected_source_hints=["visible post"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        fallback_mode="abstain",
        bullets=[
            {"text": "Abstention. The visible Bluesky post says: rose", "source_ids": ["S1"]},
            {
                "text": "No broader factual claim is made because evidence is sparse.",
                "source_ids": ["S1"],
            },
            {
                "text": "The response is a safe summary limited to source-backed context.",
                "source_ids": ["S1"],
            },
        ],
        sources=[{"id": "S1", "title": "visible post", "type": "thread", "snippet": "rose"}],
    )

    score = score_case(case, fixture)

    assert score["expected_point_recall"] == 1.0
    assert float(score["answer_usefulness_score"]) >= 0.75
    assert score["public_live_quality_pass"] == 1.0


def test_source_backed_partial_can_pass_when_link_fetch_is_unavailable() -> None:
    case = EvalCase(
        id="partial_link_summary",
        url="https://bsky.app/profile/example.com/post/3partiallink",
        category="link_context",
        expected_key_points=["linked article", "ATmosphereConf", "AT Protocol community"],
        expected_context_channels=["bluesky", "web", "link"],
        expected_source_hints=["David Imel", "ATmosphereConf"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        fallback_mode="partial",
        bullets=[
            {
                "text": (
                    "David Imel described ATmosphereConf as an AT Protocol "
                    "community gathering."
                ),
                "source_ids": ["S1"],
            },
            {
                "text": "Partial answer. The visible post summarizes the linked article.",
                "source_ids": ["S1"],
            },
            {
                "text": "No broader factual claim is made beyond the cited post.",
                "source_ids": ["S1"],
            },
        ],
        sources=[
            {
                "id": "S1",
                "title": "David Imel ATmosphereConf post",
                "type": "bluesky",
                "snippet": "ATmosphereConf linked article summary for the AT Protocol community.",
            }
        ],
    )

    score = score_case(case, fixture)

    assert score["expected_point_recall"] == 2 / 3
    assert float(score["answer_usefulness_score"]) >= 0.75
    assert score["public_live_quality_pass"] == 1.0


def test_source_backed_partial_can_pass_with_two_of_three_expected_points() -> None:
    case = EvalCase(
        id="partial_two_of_three",
        url="https://bsky.app/profile/example.com/post/3partialietf",
        category="niche_reference",
        expected_key_points=["ATP working group", "IETF charter", "AT Protocol"],
        expected_context_channels=["web", "link"],
        expected_source_hints=["AT Protocol", "IETF"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        fallback_mode="partial",
        bullets=[
            {
                "text": "An Authenticated Transfer Protocol working group was created at IETF.",
                "source_ids": ["S1"],
            },
            {
                "text": "The working group followed ATP ecosystem and IETF discussion.",
                "source_ids": ["S1"],
            },
            {
                "text": "Participation details are limited to the cited source.",
                "source_ids": ["S1"],
            },
        ],
        sources=[
            {
                "id": "S1",
                "title": "AT Protocol IETF working group article",
                "type": "web",
                "snippet": "AT Protocol ATP working group created at IETF.",
            }
        ],
    )

    score = score_case(case, fixture)

    assert score["expected_point_recall"] == 2 / 3
    assert score["public_live_quality_pass"] == 1.0


def test_sparse_context_can_pass_with_cited_image_evidence() -> None:
    case = EvalCase(
        id="sparse_image",
        url="https://bsky.app/profile/example.com/post/3sparseimage",
        category="sparse_context",
        expected_key_points=["sparse context", "safe summary", "no broader claim"],
        expected_context_channels=["bluesky", "image", "thread"],
        expected_source_hints=["visible post"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        bullets=[
            {"text": "The image shows a pink and yellow rose.", "source_ids": ["IMG"]},
            {"text": "The rose appears on a plant with green leaves.", "source_ids": ["IMG"]},
            {"text": "The visual summary stays limited to the cited image.", "source_ids": ["IMG"]},
        ],
        sources=[
            {
                "id": "IMG",
                "title": "Image description",
                "type": "image",
                "snippet": "visible post image shows a pink yellow rose with green leaves",
            }
        ],
    )

    score = score_case(case, fixture)

    assert float(score["expected_point_recall"]) >= 2 / 3
    assert score["public_live_quality_pass"] == 1.0


def test_link_context_video_is_not_forced_to_cite_image_evidence() -> None:
    case = EvalCase(
        id="video_link",
        url="https://bsky.app/profile/example.com/post/3video",
        category="link_context",
        expected_key_points=["Git City", "pixel art city", "GitHub profile"],
        expected_context_channels=["bluesky", "web", "image"],
        expected_source_hints=["Git City"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        bullets=[
            {
                "text": "Git City turns a GitHub profile into a pixel art city.",
                "source_ids": ["S1"],
            },
            {"text": "The pixel art city reflects GitHub activity.", "source_ids": ["S1"]},
            {"text": "The GitHub profile project is available online.", "source_ids": ["S1"]},
        ],
        sources=[
            {
                "id": "S1",
                "title": "Git City",
                "type": "web",
                "snippet": "Git City pixel art city GitHub profile.",
            }
        ],
    )

    score = score_case(case, fixture)

    assert score["image_evidence_used"] == 1.0
    assert score["public_live_quality_pass"] == 1.0


def test_visual_evidence_expected_point_requires_cited_image_source() -> None:
    case = EvalCase(
        id="visual",
        url="https://bsky.app/profile/example.com/post/3visual",
        category="meme_slang",
        expected_key_points=["William Morris", "visual evidence", "vibes phrase"],
        expected_context_channels=["bluesky", "image"],
        expected_source_hints=["William Morris"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        provenance="fixture_backed_public",
    )
    fixture = _fixture(
        fallback_mode="partial",
        bullets=[
            {
                "text": "Partial answer. The visible post says William Morris vibes.",
                "source_ids": ["S1"],
            },
            {"text": "No broader factual claim is made.", "source_ids": ["S1"]},
            {"text": "The response is limited to source-backed context.", "source_ids": ["S1"]},
        ],
        sources=[
            {
                "id": "S1",
                "title": "visible post",
                "type": "thread",
                "snippet": "William Morris vibes",
            }
        ],
    )

    score = score_case(case, fixture)

    assert score["image_evidence_used"] == 0.0
    assert float(score["expected_point_recall"]) < 1.0
    assert score["public_live_quality_pass"] == 0.0
