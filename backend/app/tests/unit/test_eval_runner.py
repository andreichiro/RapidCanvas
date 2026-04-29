from __future__ import annotations

from pathlib import Path

from app.eval.agents import FastApiEvalAgent
from app.eval.dataset import CachedFixture, EvalCase
from app.eval.runner import run_cached_eval, run_eval
from app.tests.unit.test_eval_metrics import make_fixture


def test_cached_eval_runner_writes_reports(tmp_path: Path) -> None:
    result = run_cached_eval(output_dir=tmp_path)
    paths = {name: Path(path) for name, path in result["paths"].items()}

    assert result["summary"]["case_count"] >= 12
    assert paths["jsonl"].exists()
    assert paths["markdown"].exists()
    assert paths["confusion_matrix"].exists()
    assert paths["graph"].exists()
    assert "prompt_injection_resistance" in paths["markdown"].read_text(encoding="utf-8")


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
