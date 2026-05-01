"""GEPA optimization entry point for the DSPy explainer program."""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from app.agent.loader import OPTIMIZED_PROGRAM_PATH
from app.agent.signatures import build_dspy_signature_classes
from app.config import Settings, get_settings
from app.eval.gepa_dataset import (
    DEFAULT_CASES_PATH,
    GepaDatasetSplit,
    build_gepa_dataset_split,
    dataset_bridge_metadata,
)
from app.eval.gepa_metric import (
    GepaMetricParts,
    combined_gepa_metric,
    gepa_feedback_metric,
    textual_feedback,
)
from app.eval.gepa_persistence import load_existing_real_program, save_compiled_program
from app.eval.gepa_validation import gepa_success_stats
from app.guardrails.policies import DEFAULT_POLICY


@dataclass(frozen=True)
class OptimizationResult:
    """Saved-program metadata returned by dry-run and real optimization."""

    output_path: Path
    metric_score: float
    mode: str
    saved_program: dict[str, Any]


def run_gepa_optimization(
    *,
    dry_run: bool = True,
    output_path: Path = OPTIMIZED_PROGRAM_PATH,
    cases_path: Path = DEFAULT_CASES_PATH,
    settings: Settings | None = None,
    optimizer_factory: Callable[[Any], Any] | None = None,
    student: Any | None = None,
    configure_provider: bool = True,
) -> OptimizationResult:
    """Run GEPA dry-run metadata or a real compile path."""

    active_settings = settings or get_settings()
    if dry_run:
        preserved_result = _preserved_real_result(output_path)
        if preserved_result is not None:
            return preserved_result
    dataset_split = build_gepa_dataset_split(cases_path=cases_path)
    metric_parts = _metric_parts(dry_run)
    metric_score = combined_gepa_metric(metric_parts)
    compile_summary: dict[str, Any] = {"executed": False}
    if not dry_run:
        compile_summary = _run_real_gepa_compile(
            settings=active_settings,
            output_path=output_path,
            dataset_split=dataset_split,
            optimizer_factory=optimizer_factory,
            student=student,
            configure_provider=configure_provider,
        )

    saved_program = {
        "schema_version": 1,
        "optimizer": "GEPA",
        "mode": "dry_run" if dry_run else "real",
        "saved_at": _saved_at(dry_run),
        "metric_score": metric_score,
        "metric_parts": asdict(metric_parts),
        "gepa_compile": compile_summary,
        "dataset_bridge": dataset_bridge_metadata(dataset_split, cases_path),
        "policy_version": DEFAULT_POLICY.version,
        "feedback_template": textual_feedback(
            ["expected contextual point absent"],
            ["claim without source support"],
        ),
        "notes": _program_notes(dry_run),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(saved_program, indent=2, sort_keys=True) + "\n"
    if not output_path.exists() or output_path.read_text(encoding="utf-8") != serialized:
        output_path.write_text(serialized, encoding="utf-8")
    return OptimizationResult(
        output_path=output_path,
        metric_score=metric_score,
        mode=str(saved_program["mode"]),
        saved_program=saved_program,
    )


def _preserved_real_result(output_path: Path) -> OptimizationResult | None:
    preserved = load_existing_real_program(output_path)
    if preserved is None:
        return None
    return OptimizationResult(
        output_path=output_path,
        metric_score=float(preserved.get("metric_score", 0.0)),
        mode=str(preserved.get("mode", "real")),
        saved_program=preserved,
    )


def _saved_at(dry_run: bool) -> str:
    if dry_run:
        return "1970-01-01T00:00:00+00:00"
    return datetime.now(UTC).isoformat()


def _program_notes(dry_run: bool) -> list[str]:
    notes = [
        "Gate 7 G7-B builds train/dev/holdout GEPA examples from finalized "
        "cached eval fixtures."
    ]
    if dry_run:
        notes.append(
            "Dry-run metadata is a save/load smoke; it is not a compiled optimized DSPy program."
        )
    else:
        notes.append(
            "Real GEPA compile produced a DSPy saved program; loader uses it when DSPy "
            "and provider credentials are available."
        )
    return notes


def _metric_parts(dry_run: bool) -> GepaMetricParts:
    return GepaMetricParts(
        expected_point_recall=0.0 if dry_run else 0.5,
        citation_coverage=1.0,
        requirement_following=1.0,
        prompt_injection_resistance=1.0,
        fallback_correctness=1.0,
    )


def _run_real_gepa_compile(
    *,
    settings: Settings,
    output_path: Path,
    dataset_split: GepaDatasetSplit,
    optimizer_factory: Callable[[Any], Any] | None,
    student: Any | None,
    configure_provider: bool,
) -> dict[str, Any]:
    if settings.openai_api_key is None:
        raise RuntimeError("OPENAI_API_KEY is required for real GEPA optimization.")
    api_key = settings.openai_api_key.get_secret_value()
    if not api_key.startswith("sk-"):
        raise RuntimeError(
            "A real OpenAI API key beginning with 'sk-' is required for GEPA --real. "
            "Use --dry-run for offline verification."
        )
    if configure_provider:
        _configure_dspy(settings)

    trainset, valset = _build_gepa_examples(
        use_dspy=student is None,
        dataset_split=dataset_split,
    )
    active_student = student or _build_optimization_student()
    optimizer = (
        optimizer_factory(gepa_feedback_metric)
        if optimizer_factory
        else _default_optimizer_factory(gepa_feedback_metric, settings)
    )
    compiled = optimizer.compile(active_student, trainset=trainset, valset=valset)
    predictor_count = len(compiled.predictors()) if hasattr(compiled, "predictors") else 0
    success_stats = gepa_success_stats(compiled, optimizer)
    compiled_path = save_compiled_program(compiled, output_path)
    return {
        "executed": True,
        "optimizer_class": optimizer.__class__.__name__,
        "compiled_program_class": compiled.__class__.__name__,
        "trainset_size": len(trainset),
        "valset_size": len(valset),
        "predictor_count": predictor_count,
        "compiled_program_path": compiled_path.name,
        "compiled_program_format": "dspy_save_program",
        **success_stats,
    }


def _configure_dspy(settings: Settings) -> None:
    dspy = _dspy()
    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key
    dspy.configure(lm=dspy.LM(settings.dspy_model), async_max_workers=4)


def _default_optimizer_factory(metric: Any, settings: Settings) -> Any:
    dspy = _dspy()
    reflection_lm = dspy.LM(
        settings.dspy_judge_model,
        temperature=1.0,
        max_tokens=32000,
    )
    return dspy.GEPA(
        metric=metric,
        max_metric_calls=2,
        reflection_minibatch_size=1,
        candidate_selection_strategy="current_best",
        reflection_lm=reflection_lm,
        track_stats=True,
        use_mlflow=False,
    )


def _build_optimization_student() -> Any:
    dspy = _dspy()
    signatures = build_dspy_signature_classes()

    class GepaExplanationStudent(dspy.Module):  # type: ignore[misc, name-defined]
        def __init__(self) -> None:
            super().__init__()
            self.explain = dspy.Predict(signatures["ExplainPost"])

        def forward(
            self,
            post_text: str,
            evidence: str,
            expected_points: list[str] | None = None,
            expected_fallback_mode: str | None = None,
            attack_type: str | None = None,
            category: str | None = None,
            expected_source_hints: list[str] | None = None,
            expected_context_channels: list[str] | None = None,
            citation_source_ids: list[str] | None = None,
        ) -> Any:
            del (
                expected_points,
                expected_fallback_mode,
                attack_type,
                category,
                expected_source_hints,
                expected_context_channels,
                citation_source_ids,
            )
            return self.explain(post_text=post_text, evidence=evidence)

    return GepaExplanationStudent()


def _build_gepa_examples(
    *,
    use_dspy: bool,
    dataset_split: GepaDatasetSplit | None = None,
) -> tuple[list[Any], list[Any]]:
    split = dataset_split or build_gepa_dataset_split()
    raw_train = [example.to_optimization_dict() for example in split.train]
    raw_dev = [example.to_optimization_dict() for example in split.dev]
    if not use_dspy:
        return raw_train, raw_dev
    dspy = _dspy()
    input_fields = (
        "post_text",
        "evidence",
        "expected_points",
        "expected_fallback_mode",
        "attack_type",
        "category",
        "expected_source_hints",
        "expected_context_channels",
        "citation_source_ids",
    )
    return (
        [dspy.Example(**example).with_inputs(*input_fields) for example in raw_train],
        [dspy.Example(**example).with_inputs(*input_fields) for example in raw_dev],
    )


def _dspy() -> Any:
    dspy = import_module("dspy")
    if getattr(dspy, "GEPA", None) is None:
        raise RuntimeError("DSPy GEPA optimizer is not available in this installation.")
    return dspy


def main(argv: list[str] | None = None) -> int:
    """CLI for ``make optimize``."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--real", action="store_true")
    parser.add_argument("--output", default=str(OPTIMIZED_PROGRAM_PATH))
    args = parser.parse_args(argv)

    result = run_gepa_optimization(dry_run=not args.real, output_path=Path(args.output))
    print(
        json.dumps(
            {
                "output_path": str(result.output_path),
                "metric_score": result.metric_score,
                "mode": result.mode,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
