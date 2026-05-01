from __future__ import annotations

import json

from pydantic import SecretStr

from app.config import Settings
from app.eval import optimize as optimize_module
from app.eval.gepa_dataset import build_gepa_dataset_examples, build_gepa_dataset_split
from app.eval.gepa_metric import GepaMetricParts, combined_gepa_metric, gepa_feedback_metric
from app.eval.optimize import (
    run_gepa_optimization,
)


def _real_program_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "optimizer": "GEPA",
        "mode": "real",
        "metric_score": 0.875,
        "gepa_compile": {"executed": True, "compiled_program_path": "program_compiled"},
    }


def test_optimizer_dry_run_saves_loadable_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from app.agent.loader import load_program

    output_path = tmp_path / "program.json"

    result = run_gepa_optimization(dry_run=True, output_path=output_path)
    loaded = load_program(
        Settings(openai_api_key=None),
        optimized_path=output_path,
        prefer_dspy=False,
    )

    assert result.output_path == output_path
    assert json.loads(output_path.read_text())["optimizer"] == "GEPA"
    assert loaded.optimized_path == output_path
    assert loaded.program.optimized_config["schema_version"] == 1


def test_optimizer_dry_run_is_deterministic_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "program.json"

    run_gepa_optimization(dry_run=True, output_path=output_path)
    first_payload = output_path.read_text()
    run_gepa_optimization(dry_run=True, output_path=output_path)
    second_payload = output_path.read_text()

    assert first_payload == second_payload
    assert json.loads(second_payload)["saved_at"] == "1970-01-01T00:00:00+00:00"


def test_combined_gepa_metric_penalizes_unsupported_claims() -> None:
    strong = combined_gepa_metric(
        GepaMetricParts(
            expected_point_recall=1.0,
            citation_coverage=1.0,
            requirement_following=1.0,
            prompt_injection_resistance=1.0,
            fallback_correctness=1.0,
            unsupported_claim_rate=0.0,
        )
    )
    weak = combined_gepa_metric(
        GepaMetricParts(
            expected_point_recall=1.0,
            citation_coverage=1.0,
            requirement_following=1.0,
            prompt_injection_resistance=1.0,
            fallback_correctness=1.0,
            unsupported_claim_rate=1.0,
        )
    )

    assert strong == 1.0
    assert weak < strong


def test_gepa_feedback_metric_supports_dspy_evaluate_two_arg_call() -> None:
    score = gepa_feedback_metric(
        {"expected_points": ["AT Protocol"], "citation_source_ids": ["S1"]},
        {"bullets": [{"text": "AT Protocol context is supported by S1.", "source_ids": ["S1"]}]},
    )

    assert isinstance(score, float)
    assert score == 1.0


def test_gepa_feedback_metric_returns_feedback_for_gepa_trace_call() -> None:
    result = gepa_feedback_metric(
        {"expected_points": ["AT Protocol"], "citation_source_ids": ["S1"]},
        {"bullets": [{"text": "Different context.", "source_ids": []}]},
        None,
        None,
        None,
    )

    assert isinstance(result, dict)
    assert isinstance(result["score"], float)
    assert result["score"] < 1.0
    assert "Missing expected points" in str(result["feedback"])
    assert "missing citation/source id S1" in str(result["feedback"])


def test_gepa_dataset_examples_are_built_from_gate6_eval_fixtures() -> None:
    examples = build_gepa_dataset_examples()
    by_id = {example.case_id: example for example in examples}
    split = build_gepa_dataset_split()
    train_dev_ids = {example.case_id for example in (*split.train, *split.dev)}
    holdout_ids = {example.case_id for example in split.holdout}

    assert len(examples) == 19
    assert by_id["public_atproto_working_group"].provenance == "fixture_backed_public"
    assert by_id["public_atproto_working_group"].post_text
    assert by_id["public_atproto_working_group"].expected_points == (
        "ATP working group",
        "IETF charter",
        "AT Protocol",
    )
    malicious_image = by_id["malicious_image_alt"]
    evidence_payload = json.loads(malicious_image.evidence)
    assert malicious_image.attack_type == "prompt_injection_image_alt"
    assert malicious_image.expected_fallback_mode == "partial"
    assert malicious_image.expected_context_channels == ("image",)
    assert "S1" in malicious_image.citation_source_ids
    assert "malicious alt text" in json.dumps(evidence_payload).lower()
    assert len(split.train) == 10
    assert len(split.dev) == 4
    assert split.holdout
    assert "malicious_image_alt" in train_dev_ids
    assert any(example.expected_fallback_mode != "none" for example in (*split.train, *split.dev))
    assert not (train_dev_ids & holdout_ids)


def test_optimizer_dry_run_records_eval_dataset_bridge_metadata(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "program.json"

    result = run_gepa_optimization(dry_run=True, output_path=output_path)
    bridge = result.saved_program["dataset_bridge"]

    assert bridge["source"] == "eval/posts.yaml plus cached fixtures"
    assert bridge["source_cases_path"] == "eval/posts.yaml"
    assert bridge["case_count"] == 19
    assert bridge["trainset_size"] == 10
    assert bridge["devset_size"] == 4
    assert bridge["holdout_size"] > 0
    assert bridge["contains_attack_or_fallback_cases"] is True
    assert "eval/fixtures/gate6/public_cases.json" in bridge["source_fixture_paths"]
    assert "eval/fixtures/cached_eval_cases.json" in bridge["source_fixture_paths"]


def test_optimizer_dry_run_preserves_existing_real_compiled_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "program.json"
    compiled_path = tmp_path / "program_compiled"
    compiled_path.mkdir()
    (compiled_path / "metadata.json").write_text("{}", encoding="utf-8")
    (compiled_path / "program.pkl").write_text("fake", encoding="utf-8")
    payload = _real_program_payload()
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_gepa_optimization(dry_run=True, output_path=output_path)

    assert result.mode == "real"
    assert result.metric_score == 0.875
    assert result.saved_program == payload
    assert json.loads(output_path.read_text(encoding="utf-8")) == payload


def test_optimizer_dry_run_does_not_preserve_incomplete_real_program(tmp_path) -> None:  # type: ignore[no-untyped-def]
    output_path = tmp_path / "program.json"
    compiled_path = tmp_path / "program_compiled"
    compiled_path.mkdir()
    payload = _real_program_payload()
    output_path.write_text(json.dumps(payload), encoding="utf-8")

    result = run_gepa_optimization(dry_run=True, output_path=output_path)

    assert result.mode == "dry_run"
    assert result.saved_program["gepa_compile"]["executed"] is False
    assert json.loads(output_path.read_text(encoding="utf-8"))["mode"] == "dry_run"


class FakeOptimizer:
    def __init__(self) -> None:
        self.compile_called = False

    def compile(self, student, *, trainset, valset):  # type: ignore[no-untyped-def]
        self.compile_called = True
        assert trainset
        assert valset
        compiled = FakeCompiledStudent()
        compiled.compiled = True
        return compiled


class FakeStudent:
    compiled = False


class FakeDetailedResults:
    val_aggregate_scores = [0.7]
    total_metric_calls = 2
    num_full_val_evals = 1


class FakeCompiledStudent(FakeStudent):
    detailed_results = FakeDetailedResults()

    def save(self, path: str, *, save_program: bool = False) -> None:
        from pathlib import Path

        assert save_program is True
        compiled_path = Path(path)
        compiled_path.mkdir(parents=True)
        (compiled_path / "metadata.json").write_text("{}")
        (compiled_path / "program.pkl").write_text("fake")


def test_optimizer_real_mode_calls_gepa_compile_with_train_and_val_sets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    optimizer = FakeOptimizer()
    output_path = tmp_path / "real-program.json"

    result = run_gepa_optimization(
        dry_run=False,
        output_path=output_path,
        settings=Settings(openai_api_key=SecretStr("sk-test-key")),
        optimizer_factory=lambda metric: optimizer,
        student=FakeStudent(),
        configure_provider=False,
    )
    payload = json.loads(output_path.read_text())

    assert optimizer.compile_called is True
    assert result.mode == "real"
    assert payload["gepa_compile"]["executed"] is True
    assert payload["gepa_compile"]["compiled_program_path"] == "real-program_compiled"
    assert (tmp_path / "real-program_compiled" / "program.pkl").exists()


def test_optimizer_real_mode_requires_provider_credentials(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="OPENAI_API_KEY"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=None),
        )


def test_optimizer_real_mode_rejects_placeholder_credentials(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="real OpenAI API key"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=SecretStr("test-key")),
        )


class FakeFailedDetails:
    val_aggregate_scores = [0.0]


class FakeFailedCompiledStudent(FakeStudent):
    detailed_results = FakeFailedDetails()


class FakeFailedOptimizer:
    failure_score = 0.0

    def compile(self, student, *, trainset, valset):  # type: ignore[no-untyped-def]
        del student, trainset, valset
        return FakeFailedCompiledStudent()


def test_optimizer_real_mode_rejects_failed_gepa_rollouts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from pytest import raises

    with raises(RuntimeError, match="no successful validation rollouts"):
        run_gepa_optimization(
            dry_run=False,
            output_path=tmp_path / "program.json",
            settings=Settings(openai_api_key=SecretStr("sk-test-key")),
            optimizer_factory=lambda metric: FakeFailedOptimizer(),
            student=FakeStudent(),
            configure_provider=False,
        )


def test_default_gepa_factory_supplies_reflection_lm(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    class FakeLM:
        def __init__(self, model: str, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.model = model
            self.kwargs = kwargs

    class FakeGEPA:
        def __init__(self, **kwargs) -> None:  # type: ignore[no-untyped-def]
            self.kwargs = kwargs

    class FakeDspy:
        LM = FakeLM
        GEPA = FakeGEPA

    monkeypatch.setattr(optimize_module, "_dspy", lambda: FakeDspy)

    optimizer = optimize_module._default_optimizer_factory(
        lambda *_args: {"score": 1.0, "feedback": "ok"},
        Settings(openai_api_key=SecretStr("sk-test-key"), dspy_judge_model="openai/test-judge"),
    )

    assert optimizer.kwargs["reflection_lm"].model == "openai/test-judge"
