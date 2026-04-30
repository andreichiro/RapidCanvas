"""Source construction helpers for API responses."""

from __future__ import annotations

from collections.abc import Sequence

from app.guardrails.policies import compact_text
from app.schemas.api import Source
from app.schemas.domain import ContextDocument, Evidence, PostContext, SourceType

POST_SOURCE_ID = "S-post"


def sources_for_response(
    post: PostContext,
    evidence: Sequence[Evidence],
    documents: Sequence[ContextDocument],
) -> list[Source]:
    """Build API sources from evidence and context documents."""

    documents_by_id = {document.id: document for document in documents}
    post_source_id = _post_source_id({item.source_id for item in evidence})
    sources: list[Source] = [post_source(post, post_source_id)]
    seen: set[str] = {post_source_id}
    for item in evidence:
        if item.source_id in seen:
            continue
        seen.add(item.source_id)
        sources.append(_source_from_evidence(post, item, documents_by_id.get(item.document_id)))
    return sources


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


def _post_source_id(evidence_source_ids: set[str]) -> str:
    if POST_SOURCE_ID not in evidence_source_ids:
        return POST_SOURCE_ID
    suffix = 1
    while f"{POST_SOURCE_ID}-{suffix}" in evidence_source_ids:
        suffix += 1
    return f"{POST_SOURCE_ID}-{suffix}"
