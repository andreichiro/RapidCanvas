"""Dataset loading for cached Bluesky explainer evaluation cases."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_PATH = REPO_ROOT / "eval" / "posts.yaml"


class EvalCase(BaseModel):
    """One assignment-style eval case with cached fixture references."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    url: str = Field(min_length=1)
    category: str = Field(min_length=1)
    expected_key_points: list[str] = Field(min_length=1)
    expected_context_channels: list[str] = Field(min_length=1)
    expected_source_hints: list[str] = Field(default_factory=list)
    fixture_paths: list[str] = Field(min_length=1)
    attack_type: str | None = None


class CachedFixture(BaseModel):
    """Cached eval fixture containing a prediction and audit metadata."""

    model_config = ConfigDict(extra="forbid")

    prediction: dict[str, Any]
    retrieved_source_hints: list[str] = Field(default_factory=list)
    trace_sequence: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    blocked_private_urls: list[str] = Field(default_factory=list)
    notes: str | None = None


def resolve_repo_path(path: str | Path) -> Path:
    """Resolve a repo-relative or absolute path."""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    resolved = (REPO_ROOT / candidate).resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"repo-relative path escapes repository root: {path}")
    return resolved


def load_eval_cases(path: str | Path = DEFAULT_CASES_PATH) -> list[EvalCase]:
    """Load JSON-compatible YAML eval cases.

    The `.yaml` extension matches the project plan. The content is deliberately
    JSON-compatible YAML so the default cached eval has no PyYAML dependency.
    """

    case_path = resolve_repo_path(path)
    payload = json.loads(case_path.read_text(encoding="utf-8"))
    cases = [EvalCase.model_validate(item) for item in payload]
    seen_ids: set[str] = set()
    for case in cases:
        if case.id in seen_ids:
            raise ValueError(f"duplicate eval case id: {case.id}")
        seen_ids.add(case.id)
    return cases


def load_cached_fixture(case: EvalCase) -> CachedFixture:
    """Load the first fixture containing this case's cached prediction."""

    fixture_errors: list[str] = []
    for fixture_path in case.fixture_paths:
        path = resolve_repo_path(fixture_path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            fixture_errors.append(f"missing fixture: {path}")
            continue

        selected = payload.get(case.id, payload)
        try:
            return CachedFixture.model_validate(selected)
        except Exception as exc:  # noqa: BLE001 - include fixture path in the validation error.
            fixture_errors.append(f"{path}: {exc}")

    raise ValueError(f"no usable cached fixture for {case.id}: {'; '.join(fixture_errors)}")
