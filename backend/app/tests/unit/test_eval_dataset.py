from __future__ import annotations

from pathlib import Path

from pytest import raises

from app.eval.dataset import load_cached_fixture, load_eval_cases, resolve_repo_path


def test_eval_dataset_has_cached_assignment_coverage() -> None:
    cases = load_eval_cases()

    assert len(cases) >= 12
    assert sum(1 for case in cases if case.fixture_paths) >= 10
    categories = {case.category for case in cases}
    assert "prompt_injection_web" in categories
    assert "low_evidence" in categories
    assert "source_safety" in categories


def test_cached_fixture_loads_prediction_for_each_case() -> None:
    for case in load_eval_cases():
        fixture = load_cached_fixture(case)

        assert fixture.prediction["bullets"]
        assert fixture.prediction["sources"]
        assert fixture.trace_sequence


def test_repo_relative_path_cannot_escape_repo_root() -> None:
    with raises(ValueError):
        resolve_repo_path(Path("../outside"))
