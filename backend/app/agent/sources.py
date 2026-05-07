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
    primary_eligible_source_ids = _primary_eligible_source_ids(documents)
    post_source_id = _post_source_id({item.source_id for item in evidence})
    sources: list[Source] = [post_source(post, post_source_id)]
    seen: set[str] = {post_source_id}
    for item in evidence:
        if item.source_id in seen:
            continue
        document = documents_by_id.get(item.document_id)
        if document is not None and document.metadata.get("citation_eligible") is False:
            continue
        if document is not None and _snippet_only(document) and not primary_eligible_source_ids:
            continue
        seen.add(item.source_id)
        sources.append(_source_from_evidence(post, item, document))
    return sources


def post_source(post: PostContext, source_id: str) -> Source:
    """Return a citeable source for the visible Bluesky post."""

    source_type: SourceType = "thread"
    return Source(
        id=source_id,
        title=f"Visible Bluesky post by {post.author}",
        url=post.url,
        type=source_type,
        snippet=compact_text(post.text, limit=260),
        quality_score=1.0,
        quality_reasons=["target_post_context"],
        citation_eligible=True,
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
        quality_score=_optional_float(document.metadata.get("source_quality_score")),
        quality_reasons=_string_list(document.metadata.get("source_quality_reasons")),
        citation_eligible=_optional_bool(document.metadata.get("citation_eligible")),
    )


def _post_source_id(evidence_source_ids: set[str]) -> str:
    if POST_SOURCE_ID not in evidence_source_ids:
        return POST_SOURCE_ID
    suffix = 1
    while f"{POST_SOURCE_ID}-{suffix}" in evidence_source_ids:
        suffix += 1
    return f"{POST_SOURCE_ID}-{suffix}"


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except Exception:
        return None


def _optional_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    if isinstance(value, str) and value:
        return [value]
    return []


def _primary_eligible_source_ids(documents: Sequence[ContextDocument]) -> set[str]:
    return {
        document.id
        for document in documents
        if document.metadata.get("citation_eligible") is True and not _snippet_only(document)
    }


def _snippet_only(document: ContextDocument) -> bool:
    return document.metadata.get("snippet_only") is True
