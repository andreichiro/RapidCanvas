"""Agent adapters used by the evaluation runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from app.eval.dataset import CachedFixture, EvalCase, load_cached_fixture


class EvalAgent(Protocol):
    """Minimal prediction boundary for cached, fake, and API-backed eval."""

    def predict(self, case: EvalCase) -> CachedFixture:
        """Return a prediction fixture for one eval case."""


class FixtureEvalAgent:
    """Fixture-backed fake agent for deterministic cached runs."""

    def predict(self, case: EvalCase) -> CachedFixture:
        return load_cached_fixture(case)


class CallableEvalAgent:
    """Adapter for tests or integration code that supply a callable predictor."""

    def __init__(self, predictor: Callable[[EvalCase], CachedFixture | dict[str, object]]) -> None:
        self._predictor = predictor

    def predict(self, case: EvalCase) -> CachedFixture:
        result = self._predictor(case)
        if isinstance(result, CachedFixture):
            return result
        return CachedFixture.model_validate(result)


class FastApiEvalAgent:
    """Evaluate the currently wired FastAPI explainer through `/api/explain`.

    This mode is explicit because it may perform live Bluesky fetches while Gate
    3 is still the default app implementation.
    """

    def __init__(self, provider: str = "openai") -> None:
        from fastapi.testclient import TestClient

        from app.main import create_app

        self._client = TestClient(create_app())
        self._provider = provider

    def predict(self, case: EvalCase) -> CachedFixture:
        response = self._client.post(
            "/api/explain",
            json={"post_url": case.url, "provider": self._provider, "include_trace": True},
        )
        response.raise_for_status()
        prediction = response.json()
        return CachedFixture(
            prediction=prediction,
            retrieved_source_hints=_source_hints(prediction),
            trace_sequence=_trace_sequence(prediction),
            unsupported_claims=[],
        )


def build_eval_agent(mode: str) -> EvalAgent:
    """Build the requested runner agent."""

    if mode in {"cached", "fake-agent"}:
        return FixtureEvalAgent()
    if mode == "api":
        return FastApiEvalAgent()
    raise ValueError(f"unsupported eval mode: {mode}")


def _source_hints(prediction: dict[str, object]) -> list[str]:
    sources = prediction.get("sources", [])
    if not isinstance(sources, list):
        return []
    hints: list[str] = []
    for source in sources:
        if isinstance(source, dict):
            hints.append(" ".join(str(source.get(key, "")) for key in ("title", "snippet")))
    return hints


def _trace_sequence(prediction: dict[str, object]) -> list[str]:
    trace = prediction.get("trace", {})
    if isinstance(trace, dict) and isinstance(trace.get("events"), list):
        events = trace["events"]
        return [str(event.get("step")) for event in events if isinstance(event, dict)]
    return ["fetch_post", "scan_input", "classify", "retrieve", "assess_trust", "validate"]

