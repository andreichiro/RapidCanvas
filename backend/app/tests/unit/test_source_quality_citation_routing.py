from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.agent.sources import sources_for_response
from app.ml.source_quality import annotate_source_quality, dedupe_equivalent_documents
from app.schemas.domain import ContextDocument, Evidence, PostContext


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


def _document(**updates: object) -> ContextDocument:
    values: dict[str, Any] = {
        "id": "DOC",
        "source_type": "web",
        "title": "AT Protocol moderation tooling launch notes",
        "url": "https://research.example/blog/atproto-moderation-tooling",
        "text": (
            "Research Example announced AT Protocol moderation tooling for Bluesky safety. "
            "The launch notes explain how the tool supports moderation labels and reviews."
        ),
        "metadata": {
            "linked_from_post": True,
            "provider": "linked_page",
            "fetch_success": True,
            "extracted_length": 151,
        },
    }
    values.update(updates)
    return ContextDocument(**values)


def test_equivalent_web_documents_keep_direct_link_primary_copy() -> None:
    post = _post()
    direct = _document(
        id="LINK",
        url="https://research.example/blog/atproto-moderation-tooling?utm=direct",
        metadata={
            "linked_from_post": True,
            "fetch_success": True,
            "source_quality_score": 0.96,
            "citation_eligible": True,
            "extracted_length": 900,
        },
    )
    search_duplicate = _document(
        id="WEB",
        url="https://www.research.example/blog/atproto-moderation-tooling",
        metadata={
            "provider": "web_search",
            "rank": 1,
            "fetch_success": True,
            "source_quality_score": 1.0,
            "citation_eligible": True,
            "extracted_length": 900,
        },
    )
    other = _document(id="OTHER", url="https://research.example/blog/other")

    annotated, _ = annotate_source_quality(post, post.text, [search_duplicate, direct, other])
    deduped = dedupe_equivalent_documents(annotated)

    assert [document.id for document in deduped] == ["LINK", "OTHER"]


def test_snippet_only_source_is_not_exposed_as_sole_public_citation() -> None:
    post = _post()
    snippet = _document(
        id="SNIP",
        text=(
            "Research Example announces AT Protocol moderation tooling for Bluesky safety "
            "with implementation details."
        ),
        metadata={
            "provider": "web_search",
            "snippet_only": True,
            "source_quality_score": 0.92,
            "source_quality_reasons": ["high_lexical_overlap"],
            "citation_eligible": True,
        },
    )
    evidence = [
        Evidence(
            id="E1",
            document_id="SNIP",
            source_id="SNIP",
            text=snippet.text,
            score=0.91,
        )
    ]

    sources = sources_for_response(post, evidence, [snippet])

    assert [source.id for source in sources] == ["S-post"]


def test_snippet_only_source_can_be_secondary_when_primary_source_is_present() -> None:
    post = _post()
    primary = _document(
        id="PRIMARY",
        metadata={"source_quality_score": 0.9, "citation_eligible": True},
    )
    snippet = _document(
        id="SNIP",
        text="Search snippet repeats Research Example AT Protocol moderation tooling details.",
        metadata={
            "provider": "web_search",
            "snippet_only": True,
            "source_quality_score": 0.91,
            "citation_eligible": True,
        },
    )
    evidence = [
        Evidence(
            id="E1",
            document_id="PRIMARY",
            source_id="PRIMARY",
            text=primary.text,
            score=0.92,
        ),
        Evidence(id="E2", document_id="SNIP", source_id="SNIP", text=snippet.text, score=0.75),
    ]

    sources = sources_for_response(post, evidence, [primary, snippet])

    assert [source.id for source in sources] == ["S-post", "PRIMARY", "SNIP"]
