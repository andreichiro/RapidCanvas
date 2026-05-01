"""Output validation and fallback construction for cited explanations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    ) -> ValidationResult:
        """Check whether a draft can be emitted without fallback."""

        issues: list[str] = []
        revised: list[BulletDraft] = []

        if fallback_mode == "none" and not (
            self._policy.min_bullets <= len(draft.bullets) <= self._policy.max_bullets
        ):
            issues.append("invalid_bullet_count")

        for bullet in draft.bullets:
            bullet_issues = self._bullet_issues(bullet, allowed_source_ids)
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
    ) -> list[Bullet]:
        """Return schema-valid bullets after removing unsafe or unsupported claims."""

        validation = self.validate(draft, allowed_source_ids, fallback_mode=fallback_mode)
        if fallback_mode == "none" and validation.is_valid:
            return _to_api_bullets(validation.revised_bullets[: self._policy.max_bullets])

        safe_bullets = validation.revised_bullets[: self._policy.max_bullets]
        if fallback_mode == "partial" and safe_bullets:
            return _to_api_bullets(
                _fill_to_minimum(
                    safe_bullets,
                    self._fallback_drafts("partial", post, post_source_id),
                    self._policy.min_bullets,
                    self._policy.max_bullets,
                )
            )

        return _to_api_bullets(
            self._fallback_drafts(fallback_mode, post, post_source_id)[: self._policy.max_bullets]
        )

    def _bullet_issues(self, bullet: BulletDraft, allowed_source_ids: set[str]) -> list[str]:
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
        return issues

    def _fallback_drafts(
        self,
        fallback_mode: FallbackMode,
        post: PostContext,
        post_source_id: str,
    ) -> list[BulletDraft]:
        visible_text = _safe_visible_post_text(post.text, self._policy)
        fallback_label = _fallback_label(fallback_mode)
        return [
            BulletDraft(
                text=f"{fallback_label} The visible Bluesky post says: {visible_text}",
                source_ids=[post_source_id],
            ),
            BulletDraft(
                text=(
                    "No broader factual claim is made because the available evidence did "
                    "not clear the citation and trust checks."
                ),
                source_ids=[post_source_id],
            ),
            BulletDraft(
                text=(
                    "The response is limited to source-backed context and keeps retrieved "
                    "instructions treated as untrusted evidence."
                ),
                source_ids=[post_source_id],
            ),
        ]


def _fallback_label(fallback_mode: FallbackMode) -> str:
    labels: dict[FallbackMode, str] = {
        "none": "Supported summary.",
        "partial": "Partial answer.",
        "safe_summary": "Safe summary.",
        "abstain": "Abstention.",
    }
    return labels[fallback_mode]


def _safe_visible_post_text(text: str, policy: GuardrailPolicy) -> str:
    visible_text = text or "The visible post has no text."
    if policy.forbidden_output_hits(visible_text):
        return (
            "The visible post contains instruction-like or credential-seeking text "
            "that was not echoed."
        )
    return compact_text(visible_text, limit=220)


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
    "leaked_instruction_or_secret",
]
