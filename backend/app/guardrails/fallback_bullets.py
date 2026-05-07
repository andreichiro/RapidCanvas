"""Fallback bullet text builders for guarded explanation output."""

from __future__ import annotations

from collections.abc import Mapping

from app.guardrails.policies import GuardrailPolicy, compact_text
from app.schemas.domain import FallbackMode, PostContext

FallbackBulletSpec = tuple[str, list[str]]


def fallback_bullet_specs(
    fallback_mode: FallbackMode,
    post: PostContext,
    post_source_id: str,
    *,
    policy: GuardrailPolicy,
    source_text_by_id: Mapping[str, str],
    allowed_source_ids: set[str],
) -> list[FallbackBulletSpec]:
    visible_text = _safe_visible_post_text(post, policy)
    if _is_sparse_visible_post(visible_text):
        return _sparse_specs(visible_text, post_source_id)
    image_source_id = _first_image_source_id(source_text_by_id, allowed_source_ids)
    if image_alt := _first_image_alt_text(post, policy):
        return _image_specs(visible_text, image_alt, post_source_id, image_source_id)
    fallback_label = _fallback_label(fallback_mode)
    return [
        (f"{fallback_label} {visible_text}", [post_source_id]),
        (f"Source-backed context: {visible_text}", [post_source_id]),
        (f"Supported context: {visible_text}", [post_source_id]),
    ]


def direct_fallback_bullet_specs(
    post: PostContext,
    post_source_id: str,
    *,
    policy: GuardrailPolicy,
) -> list[FallbackBulletSpec]:
    quoted = _quoted_visible_text(_safe_visible_post_text(post, policy))
    return [
        (f"The visible post says {quoted}.", [post_source_id]),
        (f"Visible post text: {quoted}.", [post_source_id]),
        (f"Source text available for this answer: {quoted}.", [post_source_id]),
    ]


def _sparse_specs(text: str, post_source_id: str) -> list[FallbackBulletSpec]:
    quoted = _quoted_visible_text(text)
    return [
        (f"Sparse context: the visible post only says {quoted}.", [post_source_id]),
        (f"Safe summary: {quoted} is the only cited post text here.", [post_source_id]),
        (f"No broader claim is supported beyond the visible post text {quoted}.", [post_source_id]),
    ]


def _image_specs(
    visible_text: str,
    image_alt: str,
    post_source_id: str,
    image_source_id: str,
) -> list[FallbackBulletSpec]:
    post_text = _quoted_visible_text(visible_text)
    alt_text = _quoted_visible_text(image_alt)
    image_ids = [image_source_id] if image_source_id else [post_source_id]
    return [
        (f"The visible post says {post_text}.", [post_source_id]),
        (f"The cited image evidence says {alt_text}.", image_ids),
        (
            f"The source-backed context combines {post_text} with image evidence {alt_text}.",
            [post_source_id, *image_ids],
        ),
    ]


def _fallback_label(fallback_mode: FallbackMode) -> str:
    return {
        "none": "Supported summary:",
        "partial": "Partial answer:",
        "safe_summary": "Safe summary:",
        "abstain": "Abstention:",
    }[fallback_mode]


def _safe_visible_post_text(post: PostContext, policy: GuardrailPolicy) -> str:
    visible_text = post.text or "The visible post has no text."
    if policy.forbidden_output_hits(visible_text):
        return (
            "The visible post contains instruction-like or credential-seeking text "
            "that was not echoed."
        )
    if _appears_non_english(post):
        return (
            "The visible post is not in English; this fallback does not translate or "
            "expand it beyond source-backed evidence."
        )
    return compact_text(visible_text, limit=220)


def _appears_non_english(post: PostContext) -> bool:
    langs = post.metadata.get("langs", []) if isinstance(post.metadata, dict) else []
    if isinstance(langs, str):
        langs = [langs]
    return isinstance(langs, list) and any(
        isinstance(lang, str) and lang and not lang.lower().startswith("en") for lang in langs
    )


def _is_sparse_visible_post(text: str) -> bool:
    return 0 < len([word for word in text.split() if word.strip()]) <= 3


def _quoted_visible_text(text: str) -> str:
    clean = compact_text(text, limit=160).strip().strip('"')
    return f'"{clean}"'


def _first_image_alt_text(post: PostContext, policy: GuardrailPolicy) -> str:
    for image in post.images:
        alt = compact_text(image.alt_text or "", limit=180)
        if alt and not policy.forbidden_output_hits(alt):
            return alt
    return ""


def _first_image_source_id(
    source_text_by_id: Mapping[str, str],
    allowed_source_ids: set[str],
) -> str:
    return next(
        (
            source_id
            for source_id in allowed_source_ids
            if source_id.startswith(("POST-image-", "IMG-")) and source_text_by_id.get(source_id)
        ),
        "",
    )
