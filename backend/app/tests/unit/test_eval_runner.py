from __future__ import annotations

from pathlib import Path
from typing import NoReturn

from app.eval.agents import FastApiEvalAgent
from app.eval.dataset import CachedFixture, EvalCase
from app.eval.runner import run_cached_eval, run_eval
from app.tests.unit.test_eval_metrics import make_fixture


def test_cached_eval_runner_writes_reports(tmp_path: Path) -> None:
    result = run_cached_eval(output_dir=tmp_path)
    paths = {name: Path(path) for name, path in result["paths"].items()}

    assert result["summary"]["case_count"] >= 12
    assert result["summary"]["public_fixture_case_count"] >= 10
    assert result["summary"]["public_bluesky_fixture_case_count"] >= 10
    assert result["summary"]["public_case_coverage_status"] == "fixture_backed_public_urls"
    assert result["summary"]["ragas_status"] == "skipped"
    assert result["summary"]["ragas_metric_source"] == "deterministic_proxy"
    assert result["summary"]["dspy_judge_status"] == "skipped"
    assert result["summary"]["mlflow_status"] == "not_run_by_make_eval"
    assert paths["jsonl"].exists()
    assert paths["markdown"].exists()
    assert paths["confusion_matrix"].exists()
    assert paths["graph"].exists()
    assert "prompt_injection_resistance" in paths["markdown"].read_text(encoding="utf-8")
    assert "Public fixture-backed Bluesky cases" in paths["markdown"].read_text(
        encoding="utf-8"
    )


def test_eval_runner_uses_injected_agent_and_judge(tmp_path: Path) -> None:
    class Agent:
        def predict(self, case: EvalCase) -> CachedFixture:
            return make_fixture()

    class Judge:
        def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
            return {"custom_judge_score": 0.75, "custom_judge_backend": "test"}

    result = run_eval(output_dir=tmp_path, agent=Agent(), judge=Judge())

    assert result["rows"][0]["custom_judge_score"] == 0.75
    assert result["rows"][0]["custom_judge_backend"] == "test"
    assert result["summary"]["custom_judge_score"] == 0.75


def test_api_eval_agent_records_http_failures_without_crashing() -> None:
    class Response:
        status_code = 502

        def json(self) -> dict[str, object]:
            return {"detail": {"code": "bluesky_fetch_failed"}}

    class Client:
        def post(self, url: str, *, json: object) -> Response:
            return Response()

    fixture = FastApiEvalAgent(client=Client()).predict(
        EvalCase(
            id="api_failure",
            url="https://bsky.app/profile/example.com/post/3fixedcase",
            category="source_safety",
            expected_key_points=["safe failure"],
            expected_context_channels=["thread"],
            fixture_paths=["eval/fixtures/cached_eval_cases.json"],
        )
    )

    assert fixture.prediction["trace"]["category"] == "api_error"
    assert fixture.unsupported_claims


def test_api_eval_agent_records_client_exceptions_without_crashing() -> None:
    class Client:
        def post(self, url: str, *, json: object) -> NoReturn:
            raise RuntimeError("route exploded")

    fixture = FastApiEvalAgent(client=Client()).predict(_api_case("api_exception"))

    assert fixture.prediction["trace"]["category"] == "api_error"
    assert "API client exception" in str(fixture.prediction["trace"]["warnings"][0])
    assert fixture.unsupported_claims == ["api_exception: API eval failed with client_exception"]


def test_api_eval_agent_records_non_json_error_bodies_without_crashing() -> None:
    class Response:
        status_code = 500

        def json(self) -> object:
            raise ValueError("not json")

    class Client:
        def post(self, url: str, *, json: object) -> Response:
            return Response()

    fixture = FastApiEvalAgent(client=Client()).predict(_api_case("api_non_json_error"))

    assert fixture.prediction["trace"]["category"] == "api_error"
    assert "non-JSON body" in str(fixture.prediction["trace"]["warnings"][0])
    assert fixture.unsupported_claims == ["api_non_json_error: API eval failed with 500"]


def test_api_mode_report_metadata_is_not_labeled_cached_only(tmp_path: Path) -> None:
    class Agent:
        def predict(self, case: EvalCase) -> CachedFixture:
            return make_fixture()

    result = run_eval(output_dir=tmp_path, mode="api", agent=Agent())
    report = Path(result["paths"]["markdown"]).read_text(encoding="utf-8")

    assert result["summary"]["prediction_mode"] == "api"
    assert result["summary"]["cached_case_count"] == 0.0
    assert result["summary"]["live_case_count"] == result["summary"]["case_count"]
    assert result["summary"]["api_network_calls_allowed"] is True
    assert "API/network calls allowed: `yes`" in report
    assert "performs no network or model calls" not in report


def test_model_judge_report_metadata_marks_model_calls(tmp_path: Path) -> None:
    class Agent:
        def predict(self, case: EvalCase) -> CachedFixture:
            return make_fixture()

    class Judge:
        def score(self, case: EvalCase, fixture: CachedFixture) -> dict[str, float | str]:
            return {"dspy_judge_backend": "test", "dspy_judge_expected_support": 0.5}

    result = run_eval(
        output_dir=tmp_path,
        judge_name="dspy",
        agent=Agent(),
        judge=Judge(),
    )
    report = Path(result["paths"]["markdown"]).read_text(encoding="utf-8")
    graph = Path(result["paths"]["graph"]).read_text(encoding="utf-8")

    assert result["summary"]["judge_backend"] == "dspy"
    assert result["summary"]["model_judge_calls_allowed"] is True
    assert result["summary"]["dspy_judge_expected_support"] == 0.5
    assert "Model judge calls allowed: `yes`" in report
    assert "dspy_judge_expected_support" in report
    assert "dspy_support" in graph


def _api_case(case_id: str) -> EvalCase:
    return EvalCase(
        id=case_id,
        url="https://bsky.app/profile/example.com/post/3fixedcase",
        category="source_safety",
        expected_key_points=["safe failure"],
        expected_context_channels=["thread"],
        fixture_paths=["eval/fixtures/cached_eval_cases.json"],
    )
