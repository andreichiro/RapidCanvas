"""Agent adapters used by the evaluation runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from app.eval.dataset import CachedFixture, EvalCase, load_cached_fixture


class EvalAgent(Protocol):
    """Minimal prediction boundary for cached, fake, and API-backed eval."""

    def predict(self, case: EvalCase) -> CachedFixture:
        """Return a prediction fixture for one eval case."""


class HttpResponse(Protocol):
    """Subset of an HTTP response needed by API eval."""

    status_code: int

    def json(self) -> Any:
        """Return decoded JSON."""


class HttpClient(Protocol):
    """Subset of TestClient needed by API eval."""

    def post(self, url: str, *, json: Any) -> HttpResponse:
        """POST JSON to a route."""


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

    def __init__(self, provider: str = "openai", client: HttpClient | None = None) -> None:
        self._client = client or _build_test_client()
        self._provider = provider

    def predict(self, case: EvalCase) -> CachedFixture:
        try:
            response = self._client.post(
                "/api/explain",
                json={"post_url": case.url, "provider": self._provider, "include_trace": True},
            )
        except Exception as exc:  # noqa: BLE001 - one failed API case should not abort eval.
            return _error_fixture(
                case,
                status_code=0,
                message=f"API client exception: {type(exc).__name__}: {exc}",
            )
        if response.status_code >= 400:
            return _response_error_fixture(case, response)
        try:
            prediction = response.json()
        except Exception as exc:  # noqa: BLE001 - preserve the failure as a scored eval row.
            return _error_fixture(
                case,
                status_code=response.status_code,
                message=f"API returned non-JSON success body: {type(exc).__name__}: {exc}",
            )
        if not isinstance(prediction, dict):
            return _error_fixture(
                case,
                status_code=response.status_code,
                message=f"API returned non-object JSON payload: {type(prediction).__name__}",
            )
        return CachedFixture(
            prediction=prediction,
            retrieved_source_hints=_source_hints(prediction),
            trace_sequence=_trace_sequence(prediction),
            unsupported_claims=[],
        )


def _build_test_client() -> HttpClient:
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())


def build_eval_agent(mode: str) -> EvalAgent:
    """Build the requested runner agent."""

    if mode in {"cached", "fake-agent"}:
        return FixtureEvalAgent()
    if mode == "api":
        return FastApiEvalAgent()
    raise ValueError(f"unsupported eval mode: {mode}")


def _response_error_fixture(case: EvalCase, response: HttpResponse) -> CachedFixture:
    try:
        payload = response.json()
    except Exception as exc:  # noqa: BLE001 - preserve non-JSON error bodies as eval rows.
        return _error_fixture(
            case,
            status_code=response.status_code,
            message=f"API returned HTTP {response.status_code} with non-JSON body: "
            f"{type(exc).__name__}: {exc}",
        )
    if not isinstance(payload, dict):
        payload = {"detail": payload}
    detail = payload.get("detail", payload)
    return _error_fixture(case, status_code=response.status_code, message=str(detail))


def _error_fixture(case: EvalCase, status_code: int, message: str) -> CachedFixture:
    status_label = str(status_code) if status_code > 0 else "client_exception"
    return CachedFixture(
        prediction={
            "bullets": [],
            "sources": [],
            "trace": {
                "category": "api_error",
                "fallback_mode": "abstain",
                "guardrail_flags": ["api_eval_error"],
                "warnings": [message],
                "latency_ms": 0,
                "trust_score": 0.0,
                "adapter_mode": "api_eval_error",
            },
        },
        retrieved_source_hints=[],
        trace_sequence=[
            "fetch_post",
            "scan_input",
            "classify",
            "retrieve",
            "assess_trust",
            "validate",
        ],
        unsupported_claims=[f"{case.id}: API eval failed with {status_label}"],
        notes=message,
    )


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
