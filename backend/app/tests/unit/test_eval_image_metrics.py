from __future__ import annotations

from app.eval.metrics import score_case
from app.tests.unit.test_eval_metrics import make_case, make_fixture


def test_metrics_do_not_count_ineligible_image_sources_as_used() -> None:
    case = make_case(
        category="image_context",
        expected_context_channels=["image", "thread"],
        provenance="fixture_backed_public",
    )
    fixture = make_fixture(
        sources=[
            {
                "id": "S1",
                "title": "Image description",
                "type": "image",
                "url": "https://example.test/image.jpg",
                "snippet": "supported point and second point are visible in the image",
                "citation_eligible": False,
                "metadata": {"prompt_injection_flags": ["ignore_previous_instructions"]},
            }
        ]
    )

    score = score_case(case, fixture)

    assert score["image_evidence_used"] == 0.0
    assert score["public_live_quality_pass"] == 0.0


def test_metrics_do_not_count_empty_image_diagnostics_as_used() -> None:
    case = make_case(
        category="image_context",
        expected_context_channels=["image", "thread"],
        provenance="fixture_backed_public",
    )
    fixture = make_fixture(
        sources=[
            {
                "id": "S1",
                "title": "Image diagnostic",
                "type": "image",
                "url": "https://example.test/image.jpg",
                "snippet": "No image description available.",
                "metadata": {"vision_warning": "image_vision_unavailable_no_alt_text:1"},
            }
        ]
    )

    score = score_case(case, fixture)

    assert score["image_evidence_used"] == 0.0
    assert score["public_live_quality_pass"] == 0.0
