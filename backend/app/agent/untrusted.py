"""Helpers for labeling external text as untrusted evidence."""

from __future__ import annotations

from collections.abc import Sequence

from app.schemas.domain import Evidence, PostContext, SourceType


def scan_inputs(
    post: PostContext,
    evidence: Sequence[Evidence],
    source_types: dict[str, SourceType],
) -> list[tuple[str, str]]:
    """Return labeled content passed to prompt-injection detectors."""

    inputs = [
        ("UNTRUSTED_POST_TEXT", post.text),
        *(("UNTRUSTED_THREAD_CONTEXT", text) for text in post.parent_texts),
        *(("UNTRUSTED_THREAD_CONTEXT", text) for text in post.quoted_texts),
        *(("UNTRUSTED_IMAGE_ALT_TEXT", image.alt_text or "") for image in post.images),
    ]
    inputs.extend((evidence_untrusted_label(item, source_types), item.text) for item in evidence)
    return inputs


def evidence_untrusted_label(item: Evidence, source_types: dict[str, SourceType]) -> str:
    """Map a retrieved evidence chunk to the correct untrusted-content label."""

    source_type = source_types.get(item.document_id)
    if source_type == "image":
        return "UNTRUSTED_IMAGE_ALT_TEXT"
    if source_type in {"thread", "bluesky"}:
        return "UNTRUSTED_THREAD_CONTEXT"
    return "UNTRUSTED_WEB_CONTEXT"
