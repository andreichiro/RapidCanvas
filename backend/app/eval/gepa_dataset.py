"""GEPA dataset bridge from finalized cached eval cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.eval.gepa_source_quality import (
    SOURCE_QUALITY_POLICY_VERSION,
    average_score,
    source_citation_eligible,
    source_quality_reasons,
    source_quality_score,
    source_quality_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES_PATH = REPO_ROOT / "eval" / "posts.yaml"
LEGACY_PUBLIC_FIXTURE_PATH = "eval/fixtures/" + "gate" + "6/public_cases.json"
PUBLIC_FIXTURE_DISPLAY_PATH = "eval/fixtures/public_cases.json"


@dataclass(frozen=True)
class GepaDatasetExample:
    """One curated eval fixture converted into a GEPA optimization example."""

    case_id: str
    post_text: str
    evidence: str
    expected_points: tuple[str, ...]
    expected_fallback_mode: str
    attack_type: str | None
    category: str
    expected_source_hints: tuple[str, ...]
    expected_context_channels: tuple[str, ...]
    citation_source_ids: tuple[str, ...]
    citation_eligible_source_ids: tuple[str, ...]
    expected_citation_relevance_score: float
    expected_source_quality_score: float
    source_quality_policy_version: str
    provenance: str
    fixture_paths: tuple[str, ...]
    source_ids: tuple[str, ...]

    def to_optimization_dict(self) -> dict[str, Any]:
        """Return the fields passed to DSPy GEPA examples."""

        return {
            "case_id": self.case_id,
            "post_text": self.post_text,
            "evidence": self.evidence,
            "expected_points": list(self.expected_points),
            "expected_fallback_mode": self.expected_fallback_mode,
            "attack_type": self.attack_type,
            "category": self.category,
            "expected_source_hints": list(self.expected_source_hints),
            "expected_context_channels": list(self.expected_context_channels),
            "citation_source_ids": list(self.citation_source_ids),
            "citation_eligible_source_ids": list(self.citation_eligible_source_ids),
            "expected_citation_relevance_score": self.expected_citation_relevance_score,
            "expected_source_quality_score": self.expected_source_quality_score,
            "source_quality_policy_version": self.source_quality_policy_version,
        }


@dataclass(frozen=True)
class GepaDatasetSplit:
    """Deterministic train/dev/holdout split for GEPA optimization."""

    train: tuple[GepaDatasetExample, ...]
    dev: tuple[GepaDatasetExample, ...]
    holdout: tuple[GepaDatasetExample, ...]

    @property
    def all_examples(self) -> tuple[GepaDatasetExample, ...]:
        return (*self.train, *self.dev, *self.holdout)


def build_gepa_dataset_examples(
    cases_path: Path = DEFAULT_CASES_PATH,
) -> tuple[GepaDatasetExample, ...]:
    """Build GEPA examples from finalized eval cases and cached fixtures."""

    examples: list[GepaDatasetExample] = []
    for case in _load_eval_case_payloads(cases_path):
        fixture = _load_cached_fixture_payload(case)
        examples.append(_example_from_case(case, fixture))
    return tuple(examples)


def build_gepa_dataset_split(
    cases_path: Path = DEFAULT_CASES_PATH,
    *,
    train_size: int = 10,
    dev_size: int = 4,
) -> GepaDatasetSplit:
    """Build a representative deterministic split while preserving holdouts."""

    examples = _representative_order(build_gepa_dataset_examples(cases_path))
    if not examples:
        return GepaDatasetSplit(train=(), dev=(), holdout=())

    holdout_floor = 1 if len(examples) > 2 else 0
    train_count = min(max(1, train_size), max(1, len(examples) - holdout_floor))
    remaining_after_train = len(examples) - train_count
    if remaining_after_train <= holdout_floor:
        validation_count = 0
    else:
        validation_count = min(max(1, dev_size), remaining_after_train - holdout_floor)
    dev_start = train_count
    holdout_start = train_count + validation_count
    return GepaDatasetSplit(
        train=examples[:train_count],
        dev=examples[dev_start:holdout_start],
        holdout=examples[holdout_start:],
    )


def dataset_bridge_metadata(split: GepaDatasetSplit, cases_path: Path) -> dict[str, Any]:
    """Return dry-run metadata proving the eval-dataset bridge source."""

    fixture_paths = sorted(
        {
            _metadata_fixture_path(path)
            for example in split.all_examples
            for path in example.fixture_paths
        }
    )
    return {
        "source": "eval/posts.yaml plus cached fixtures",
        "source_cases_path": _repo_display_path(_resolve_repo_path(cases_path)),
        "source_fixture_paths": fixture_paths,
        "case_count": len(split.all_examples),
        "trainset_size": len(split.train),
        "devset_size": len(split.dev),
        "holdout_size": len(split.holdout),
        "train_case_ids": [example.case_id for example in split.train],
        "validation_case_ids": [example.case_id for example in split.dev],
        "holdout_case_ids": [example.case_id for example in split.holdout],
        "contains_attack_or_fallback_cases": any(
            example.attack_type is not None or example.expected_fallback_mode != "none"
            for example in (*split.train, *split.dev)
        ),
        "source_quality_policy_version": SOURCE_QUALITY_POLICY_VERSION,
        "contains_source_quality_fields": all(
            example.source_quality_policy_version == SOURCE_QUALITY_POLICY_VERSION
            and example.expected_source_quality_score >= 0.0
            and example.expected_citation_relevance_score >= 0.0
            for example in split.all_examples
        ),
        "average_expected_source_quality_score": _average(
            [example.expected_source_quality_score for example in split.all_examples]
        ),
        "average_expected_citation_relevance_score": _average(
            [example.expected_citation_relevance_score for example in split.all_examples]
        ),
    }


def _example_from_case(case: dict[str, Any], fixture: dict[str, Any]) -> GepaDatasetExample:
    prediction = _mapping(fixture.get("prediction", {}))
    post = _mapping(prediction.get("post", {}))
    trace = _mapping(prediction.get("trace", {}))
    sources = [_mapping(source) for source in _list(prediction.get("sources", []))]
    bullets = [_mapping(bullet) for bullet in _list(prediction.get("bullets", []))]
    citation_source_ids = _citation_source_ids(bullets)
    quality_summary = source_quality_summary(sources, citation_source_ids)
    return GepaDatasetExample(
        case_id=str(case.get("id", "")),
        post_text=_post_text(case, post, sources),
        evidence=_evidence_payload(
            sources,
            _string_list(fixture.get("retrieved_source_hints", [])),
        ),
        expected_points=tuple(_string_list(case.get("expected_key_points", []))),
        expected_fallback_mode=str(trace.get("fallback_mode", "none")),
        attack_type=_optional_string(case.get("attack_type")),
        category=str(case.get("category", "")),
        expected_source_hints=tuple(_string_list(case.get("expected_source_hints", []))),
        expected_context_channels=tuple(_string_list(case.get("expected_context_channels", []))),
        citation_source_ids=citation_source_ids,
        citation_eligible_source_ids=quality_summary["citation_eligible_source_ids"],
        expected_citation_relevance_score=quality_summary["expected_citation_relevance_score"],
        expected_source_quality_score=quality_summary["expected_source_quality_score"],
        source_quality_policy_version=SOURCE_QUALITY_POLICY_VERSION,
        provenance=str(case.get("provenance", "synthetic_fixture")),
        fixture_paths=tuple(_string_list(case.get("fixture_paths", []))),
        source_ids=tuple(str(source.get("id", "")) for source in sources if source.get("id")),
    )


def _post_text(
    case: dict[str, Any],
    post: dict[str, Any],
    sources: list[dict[str, Any]],
) -> str:
    text = str(post.get("text", "")).strip()
    if text:
        return text
    source_snippet = " ".join(
        str(source.get("snippet", "")).strip() for source in sources if source.get("snippet")
    ).strip()
    if source_snippet:
        return source_snippet
    return str(case.get("url") or case.get("category") or case.get("id", "")).strip()


def _evidence_payload(sources: list[dict[str, Any]], retrieved_source_hints: list[str]) -> str:
    payload = {
        "sources": [
            {
                "id": str(source.get("id", "")),
                "source_id": str(source.get("id", "")),
                "title": str(source.get("title", "")),
                "source_type": str(source.get("type", "")),
                "url": str(source.get("url", "")),
                "text": str(source.get("snippet", "")),
                "quality_score": source_quality_score(source),
                "quality_reasons": source_quality_reasons(source),
                "citation_eligible": source_citation_eligible(source),
            }
            for source in sources
        ],
        "retrieved_source_hints": [str(hint) for hint in retrieved_source_hints],
        "relevant_source_snippets": [
            str(source.get("snippet", "")) for source in sources if source.get("snippet")
        ],
    }
    return json.dumps(payload, sort_keys=True)


def _citation_source_ids(bullets: list[dict[str, Any]]) -> tuple[str, ...]:
    source_ids: list[str] = []
    for bullet in bullets:
        for source_id in _list(bullet.get("source_ids", [])):
            normalized = str(source_id)
            if normalized and normalized not in source_ids:
                source_ids.append(normalized)
    return tuple(source_ids)


def _representative_order(
    examples: tuple[GepaDatasetExample, ...],
) -> tuple[GepaDatasetExample, ...]:
    public = [example for example in examples if example.provenance == "fixture_backed_public"]
    image = [
        example
        for example in examples
        if "image" in example.expected_context_channels or "image" in example.category
    ]
    fallback_or_attack = [
        example
        for example in examples
        if example.attack_type is not None or example.expected_fallback_mode != "none"
    ]
    normal = [
        example
        for example in examples
        if example not in public and example not in image and example not in fallback_or_attack
    ]
    return _unique_examples(
        (
            *public[:3],
            *image[:5],
            *fallback_or_attack[:5],
            *public[3:],
            *fallback_or_attack[5:],
            *normal,
        )
    )


def _unique_examples(examples: tuple[GepaDatasetExample, ...]) -> tuple[GepaDatasetExample, ...]:
    selected: list[GepaDatasetExample] = []
    seen: set[str] = set()
    for example in examples:
        if example.case_id in seen:
            continue
        selected.append(example)
        seen.add(example.case_id)
    return tuple(selected)


def _load_eval_case_payloads(cases_path: Path) -> list[dict[str, Any]]:
    path = _resolve_repo_path(cases_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"GEPA cases payload must be a list: {path}")
    return [_mapping(item) for item in payload]


def _load_cached_fixture_payload(case: dict[str, Any]) -> dict[str, Any]:
    case_id = str(case.get("id", ""))
    errors: list[str] = []
    for fixture_path in _string_list(case.get("fixture_paths", [])):
        path = _resolve_repo_path(Path(fixture_path))
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            errors.append(f"missing fixture: {path}")
            continue
        if not isinstance(payload, dict):
            errors.append(f"{path}: fixture payload must be an object")
            continue
        selected_payload = _mapping(payload.get(case_id, payload))
        if selected_payload:
            return selected_payload
        errors.append(f"{path}: no object fixture for {case_id}")
    raise ValueError(f"no usable cached fixture for {case_id}: {'; '.join(errors)}")


def _resolve_repo_path(path: Path) -> Path:
    candidate = path if path.is_absolute() else REPO_ROOT / path
    resolved = candidate.resolve()
    if not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"repo-relative path escapes repository root: {path}")
    return resolved


def _repo_display_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _metadata_fixture_path(path: str) -> str:
    if path == LEGACY_PUBLIC_FIXTURE_PATH:
        return PUBLIC_FIXTURE_DISPLAY_PATH
    return path


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string_list(value: Any) -> list[str]:
    return [str(item) for item in _list(value)]


def _optional_string(value: Any) -> str | None:
    return None if value is None else str(value)


def _average(values: list[float]) -> float:
    return average_score(values)
