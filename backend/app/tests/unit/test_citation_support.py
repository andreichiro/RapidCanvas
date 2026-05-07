from __future__ import annotations

from app.guardrails.citation_support import (
    CitationSupportResult,
    check_bullet_support,
)
from app.guardrails.output import BulletDraft, ExplanationDraft, OutputGuardrail


def test_material_terms_support_named_entity_and_date_claim() -> None:
    result = check_bullet_support(
        "Python 3.13 changed CPython JIT configuration in 2026.",
        ["S1"],
        {"S1": "Python 3.13 release notes describe CPython JIT configuration changes in 2026."},
    )

    assert result == CitationSupportResult(is_supported=True, issues=[])


def test_off_topic_citation_is_rejected_even_when_a_source_id_exists() -> None:
    result = check_bullet_support(
        "The Mariners ceremony explains the Ichiro quote.",
        ["S1"],
        {"S1": "Ichiro Suzuki trading card price catalog marketplace checklist."},
    )

    assert result.is_supported is False
    assert "weak_citation_support" in result.issues
    assert "off_topic_citation" in result.issues


def test_snippet_only_source_cannot_support_broad_causal_claim_alone() -> None:
    result = check_bullet_support(
        "The policy passed because the committee confirmed the final vote.",
        ["S1"],
        {"S1": "The committee confirmed the final vote."},
        snippet_only_source_ids={"S1"},
    )

    assert result.is_supported is False
    assert "needs_primary_source" in result.issues


def test_snippet_only_source_cannot_support_announcement_claim_alone() -> None:
    result = check_bullet_support(
        "Research Example announced AT Protocol moderation tooling.",
        ["S1"],
        {"S1": "Research Example announced AT Protocol moderation tooling."},
        snippet_only_source_ids={"S1"},
    )

    assert result.is_supported is False
    assert "needs_primary_source" in result.issues


def test_year_claim_requires_same_year_in_cited_source() -> None:
    result = check_bullet_support(
        "Maryland passed the grocery pricing rule in 2026.",
        ["S1"],
        {"S1": "Maryland approved the grocery pricing rule after committee review."},
    )

    assert result.is_supported is False
    assert "unsupported_claim" in result.issues


def test_named_entity_claim_requires_entity_overlap() -> None:
    result = check_bullet_support(
        "Maryland passed the grocery pricing rule.",
        ["S1"],
        {"S1": "California passed the grocery pricing rule."},
    )

    assert result.is_supported is False
    assert "weak_citation_support" in result.issues
    assert "off_topic_citation" in result.issues


def test_causal_claim_requires_causal_support_marker() -> None:
    result = check_bullet_support(
        "The policy changed because the committee confirmed the final vote.",
        ["S1"],
        {"S1": "The policy changed after the committee confirmed the final vote."},
    )

    assert result.is_supported is False
    assert "unsupported_claim" in result.issues


def test_primary_source_can_support_broad_claim_when_one_citation_is_not_snippet_only() -> None:
    result = check_bullet_support(
        "The policy passed because the committee confirmed the final vote.",
        ["S1", "S2"],
        {
            "S1": "The committee confirmed the final vote.",
            "S2": "The policy passed because the committee confirmed the final vote.",
        },
        snippet_only_source_ids={"S1"},
    )

    assert result.is_supported is True
    assert result.issues == []


def test_unrelated_primary_does_not_mask_snippet_only_broad_claim() -> None:
    result = check_bullet_support(
        "The policy passed because the committee confirmed the final vote.",
        ["S1", "S2"],
        {
            "S1": "The policy passed because the committee confirmed the final vote.",
            "S2": "Primary source lists committee membership and meeting calendar only.",
        },
        snippet_only_source_ids={"S1"},
    )

    assert result.is_supported is False
    assert "needs_primary_source" in result.issues


def test_sparse_visible_post_can_support_conservative_meta_summary() -> None:
    result = check_bullet_support(
        'Sparse context: the visible post only says "rose".',
        ["S-post"],
        {"S-post": "rose"},
    )

    assert result.is_supported is True
    assert result.issues == []


def test_output_guardrail_uses_citation_support_map() -> None:
    draft = ExplanationDraft(
        bullets=[
            BulletDraft(
                text="Python 3.13 changed CPython JIT configuration.",
                source_ids=["S1"],
            ),
            BulletDraft(
                text="The Mariners ceremony explains the Ichiro quote.",
                source_ids=["S2"],
            ),
            BulletDraft(
                text="The release notes describe build options.",
                source_ids=["S1"],
            ),
        ]
    )

    validation = OutputGuardrail().validate(
        draft,
        {"S1", "S2"},
        source_text_by_id={
            "S1": (
                "Python 3.13 release notes describe CPython JIT configuration changes "
                "and build options."
            ),
            "S2": "Ichiro Suzuki trading card price catalog marketplace checklist.",
        },
    )

    assert validation.is_valid is False
    assert "weak_citation_support" in validation.issues
    assert "off_topic_citation" in validation.issues
    assert [bullet.text for bullet in validation.revised_bullets] == [
        "Python 3.13 changed CPython JIT configuration.",
        "The release notes describe build options.",
    ]
