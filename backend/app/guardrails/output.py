"""Output validation and fallback construction for cited explanations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.guardrails.citation_support import check_bullet_support
from app.guardrails.fallback_bullets import (
    direct_fallback_bullet_specs,
    fallback_bullet_specs,
)
from app.guardrails.policies import DEFAULT_POLICY, GuardrailPolicy, compact_text
from app.schemas.api import Bullet
from app.schemas.domain import FallbackMode, PostContext


class GuardrailModel(BaseModel):
    """Base model for internal guardrail payloads."""

    model_config = ConfigDict(extra="forbid")


class BulletDraft(GuardrailModel):
    """Structured bullet proposed by a DSPy signature or deterministic test runner."""

    text: str = Field(min_length=1)
    source_ids: list[str] = Field(default_factory=list)


class ExplanationDraft(GuardrailModel):
    """Structured candidate explanation before final API validation."""

    bullets: list[BulletDraft] = Field(default_factory=list)


class ValidationResult(GuardrailModel):
    """Guardrail validation result and optional repaired bullets."""

    is_valid: bool
    issues: list[str] = Field(default_factory=list)
    revised_bullets: list[BulletDraft] = Field(default_factory=list)


class OutputGuardrail:
    """Validate model output against citation, shape, and prompt-leakage rules."""

    def __init__(self, policy: GuardrailPolicy = DEFAULT_POLICY) -> None:
        self._policy = policy

    def validate(
        self,
        draft: ExplanationDraft,
        allowed_source_ids: set[str],
        *,
        fallback_mode: FallbackMode = "none",
        source_text_by_id: Mapping[str, str] | None = None,
        snippet_only_source_ids: set[str] | None = None,
    ) -> ValidationResult:
        """Check whether a draft can be emitted without fallback."""

        issues: list[str] = []
        revised: list[BulletDraft] = []

        if fallback_mode == "none" and not (
            self._policy.min_bullets <= len(draft.bullets) <= self._policy.max_bullets
        ):
            issues.append("invalid_bullet_count")

        for bullet in draft.bullets:
            bullet_issues = self._bullet_issues(
                bullet,
                allowed_source_ids,
                source_text_by_id=source_text_by_id,
                snippet_only_source_ids=snippet_only_source_ids,
            )
            if bullet_issues:
                issues.extend(bullet_issues)
                continue
            revised.append(
                BulletDraft(
                    text=compact_text(bullet.text, limit=420),
                    source_ids=_dedupe_source_ids(bullet.source_ids),
                )
            )

        return ValidationResult(
            is_valid=len(issues) == 0,
            issues=_dedupe_strings(issues),
            revised_bullets=revised,
        )

    def repair(
        self,
        draft: ExplanationDraft,
        allowed_source_ids: set[str],
        *,
        fallback_mode: FallbackMode,
        post: PostContext,
        post_source_id: str,
        source_text_by_id: Mapping[str, str] | None = None,
        snippet_only_source_ids: set[str] | None = None,
    ) -> list[Bullet]:
        """Return schema-valid bullets after removing unsafe or unsupported claims."""

        support_text = dict(source_text_by_id or {})
        support_text.setdefault(post_source_id, post.text)
        validation = self.validate(
            draft,
            allowed_source_ids,
            fallback_mode=fallback_mode,
            source_text_by_id=support_text,
            snippet_only_source_ids=snippet_only_source_ids,
        )
        if fallback_mode == "none" and validation.is_valid:
            return _to_api_bullets(validation.revised_bullets[: self._policy.max_bullets])

        fallback_drafts = self._validated_fallback_drafts(
            fallback_mode,
            post,
            post_source_id,
            allowed_source_ids,
            support_text,
            snippet_only_source_ids,
        )
        safe_bullets = validation.revised_bullets[: self._policy.max_bullets]
        if fallback_mode == "partial" and safe_bullets:
            return _to_api_bullets(
                _fill_to_minimum(
                    safe_bullets,
                    fallback_drafts,
                    self._policy.min_bullets,
                    self._policy.max_bullets,
                )
            )

        return _to_api_bullets(fallback_drafts[: self._policy.max_bullets])

    def _validated_fallback_drafts(
        self,
        fallback_mode: FallbackMode,
        post: PostContext,
        post_source_id: str,
        allowed_source_ids: set[str],
        source_text_by_id: Mapping[str, str],
        snippet_only_source_ids: set[str] | None,
    ) -> list[BulletDraft]:
        fallback = _drafts_from_specs(
            fallback_bullet_specs(
                fallback_mode,
                post,
                post_source_id,
                policy=self._policy,
                source_text_by_id=source_text_by_id,
                allowed_source_ids=allowed_source_ids,
            )
        )
        validation = self.validate(
            ExplanationDraft(bullets=fallback),
            allowed_source_ids | {post_source_id},
            fallback_mode=fallback_mode,
            source_text_by_id=source_text_by_id,
            snippet_only_source_ids=snippet_only_source_ids,
        )
        if len(validation.revised_bullets) >= self._policy.min_bullets:
            return validation.revised_bullets[: self._policy.max_bullets]
        direct = _drafts_from_specs(
            direct_fallback_bullet_specs(post, post_source_id, policy=self._policy)
        )
        direct_validation = self.validate(
            ExplanationDraft(bullets=direct),
            allowed_source_ids | {post_source_id},
            fallback_mode=fallback_mode,
            source_text_by_id=source_text_by_id,
            snippet_only_source_ids=snippet_only_source_ids,
        )
        if len(direct_validation.revised_bullets) >= self._policy.min_bullets:
            return direct_validation.revised_bullets[: self._policy.max_bullets]
        return direct[: self._policy.min_bullets]

    def _bullet_issues(
        self,
        bullet: BulletDraft,
        allowed_source_ids: set[str],
        *,
        source_text_by_id: Mapping[str, str] | None,
        snippet_only_source_ids: set[str] | None,
    ) -> list[str]:
        issues: list[str] = []
        if not bullet.source_ids:
            issues.append("uncited_output")
        unknown_sources = [
            source_id for source_id in bullet.source_ids if source_id not in allowed_source_ids
        ]
        if unknown_sources:
            issues.append("unknown_citation")
        if self._policy.forbidden_output_hits(bullet.text):
            issues.append("leaked_instruction_or_secret")
            issues.append("unsafe_echo")
        if text_appears_non_english(bullet.text):
            issues.append("non_english_output")
        if not issues and source_text_by_id is not None:
            support = check_bullet_support(
                bullet.text,
                bullet.source_ids,
                dict(source_text_by_id),
                snippet_only_source_ids=snippet_only_source_ids,
            )
            issues.extend(support.issues)
        return issues

def _drafts_from_specs(specs: list[tuple[str, list[str]]]) -> list[BulletDraft]:
    return [BulletDraft(text=text, source_ids=source_ids) for text, source_ids in specs]


def _appears_non_english(post: PostContext) -> bool:
    langs = post.metadata.get("langs", []) if isinstance(post.metadata, dict) else []
    if isinstance(langs, str):
        langs = [langs]
    if isinstance(langs, list) and any(
        isinstance(lang, str) and lang and not lang.lower().startswith("en") for lang in langs
    ):
        return True
    return text_appears_non_english(post.text)


def text_appears_non_english(text: str) -> bool:
    """Conservative language check for output bullets that must be English.

    The product contract is English explanations. This intentionally catches
    obvious Spanish/Portuguese passthrough while avoiding broad language ID
    dependencies in the hot path.
    """

    lowered = f" {text.lower()} "
    if not lowered.strip():
        return False
    non_ascii = any(ord(character) > 127 for character in lowered)
    markers = (
        " el ",
        " la ",
        " los ",
        " las ",
        " un ",
        " una ",
        " de ",
        " del ",
        " en ",
        " que ",
        " con ",
        " por ",
        " para ",
        " hoy,",
        " ganó",
        " sacó",
        " está",
        " semifinales",
        " afición",
        " bandera",
        " victoria",
        " jugadores",
        " incluyendo",
    )
    marker_count = sum(1 for marker in markers if marker in lowered)
    return (non_ascii and marker_count >= 1) or marker_count >= 4


def _fill_to_minimum(
    bullets: list[BulletDraft],
    fallback_bullets: list[BulletDraft],
    minimum: int,
    maximum: int,
) -> list[BulletDraft]:
    filled = list(bullets)
    for fallback in fallback_bullets:
        if len(filled) >= minimum:
            break
        filled.append(fallback)
    return filled[:maximum]


def _to_api_bullets(drafts: list[BulletDraft]) -> list[Bullet]:
    return [Bullet(text=draft.text, source_ids=draft.source_ids) for draft in drafts]


def _dedupe_source_ids(source_ids: list[str]) -> list[str]:
    return _dedupe_strings(source_ids)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            deduped.append(value)
    return deduped


OutputIssue = Literal[
    "invalid_bullet_count",
    "uncited_output",
    "unknown_citation",
    "unsupported_claim",
    "weak_citation_support",
    "off_topic_citation",
    "needs_primary_source",
    "leaked_instruction_or_secret",
    "unsafe_echo",
    "non_english_output",
]
