"""Source construction helpers for API responses."""

from __future__ import annotations

from collections.abc import Sequence

from app.guardrails.policies import compact_text
from app.schemas.api import Source
from app.schemas.domain import ContextDocument, Evidence, PostContext, SourceType


def sources_for_response(
    post: PostContext,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
) -> list[Source]:
    """Build API sources from evidence and context documents."""

    if not evidence:
        return [post_source(post, "S1")]

    documents_by_id = {document.id: document for document in documents}
    sources: list[Source] = []
    seen: set[str] = set()
    for item in evidence:
        if item.source_id in seen:
            continue
        seen.add(item.source_id)
        sources.append(_source_from_evidence(post, item, documents_by_id.get(item.document_id)))
    return sources or [post_source(post, "S1")]


def post_source(post: PostContext, source_id: str) -> Source:
    """Return a citeable source for the visible Bluesky post."""

    source_type: SourceType = "thread"
    return Source(
        id=source_id,
        title=f"Bluesky post by {post.author}",
        url=post.url,
        type=source_type,
        snippet=compact_text(post.text, limit=260),
    )


def _source_from_evidence(
    post: PostContext,
    evidence: Evidence,
    document: ContextDocument | None,
) -> Source:
    if document is None:
        return post_source(post, evidence.source_id)
    return Source(
        id=evidence.source_id,
        title=document.title,
        url=document.url,
        type=document.source_type,
        snippet=compact_text(document.text, limit=260),
    )

