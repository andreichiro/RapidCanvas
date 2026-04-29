# Gate 3 Final Review

Date: 2026-04-29
Scope: real Bluesky post fetch, trace-marked deterministic dev adapters, `/api/explain` product slice, frontend submit/result path, API/browser user-style verification, tests, docs, and requirement-matrix updates.

## Review Result

Gate 3 is complete for its accepted definition of done.

No blocking findings were found.

## What Was Implemented

- `backend/app/clients/bsky.py` implements a read-only Bluesky client using the `atproto` SDK.
- `backend/app/agent/dev_adapter.py` implements the Gate 3 vertical slice:
  - real Bluesky post/thread fetch;
  - schema-valid 3-bullet safe summary;
  - cited sources from fetched thread context;
  - explicit `adapter_mode=deterministic_dev`;
  - explicit Search/RAG and DSPy adapter warnings;
  - `fallback_mode=safe_summary`;
  - guardrail flags showing the result is not final Search/RAG or DSPy synthesis.
- `backend/app/api/routes.py`, `backend/app/deps.py`, and `backend/app/main.py` wire the explainer into `POST /api/explain`.
- `backend/app/schemas/api.py` exposes adapter trace fields so temporary adapter use is visible to API clients, frontend, eval, and review.
- `frontend/src/App.tsx` now submits a Bluesky URL to the backend, renders 3 cited bullets, shows sources, and exposes trust/fallback/adapter trace details.
- `frontend/src/api/client.ts` provides typed API calls for providers and explanations.
- `docs/current_handoff.md`, `README.md`, `AGENTS.md`, and `docs/requirements_matrix.md` now describe the Gate 3 state and non-final adapter boundary.

## Correctness Review

- The route performs real Bluesky fetching for public post URLs before producing a response.
- Search/RAG and DSPy behavior is intentionally deterministic and non-final, and the response marks that clearly in trace.
- Normal Gate 3 responses have exactly 3 bullets and at least one citation per bullet.
- Sources are derived from the fetched Bluesky target post and parent thread context.
- Bluesky fetch failures map to `502` with a structured `bluesky_fetch_failed` error.
- Invalid Bluesky URL shape still returns FastAPI validation errors.
- The provider route remains read-only and does not require optional provider keys.

## Maintainability Review

- The real Bluesky client is isolated from the adapter, so later gates can replace Search/RAG and DSPy without changing the public route contract.
- The adapter is small and named as a Gate 3 dev adapter, reducing the risk that it is mistaken for final agent behavior.
- API models remain the shared boundary for backend, frontend, eval, and future agent work.
- The frontend uses a typed API client rather than duplicating response parsing inside UI code.
- The implementation avoids broad control flow and keeps file sizes within the registered review thresholds.

## User-Style API Review

A local backend was started and exercised through HTTP with the public sample URL:

```text
POST /api/explain
https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y
```

Observed response summary:

```json
{
  "author": "bsky.app",
  "bullet_count": 3,
  "source_count": 2,
  "adapter_mode": "deterministic_dev",
  "fallback_mode": "safe_summary",
  "warnings": [
    "real_bluesky_fetch_enabled",
    "search_rag_uses_deterministic_dev_adapter",
    "dspy_uses_deterministic_dev_adapter"
  ]
}
```

## Browser Review

The in-app browser was used against `http://127.0.0.1:5174/` with the local backend running.

Verified visible behavior:

- app shell loads;
- provider selector renders configured/skipped provider state;
- Explain button submits the default Bluesky URL;
- 3 cited bullets render;
- source list renders `S1` and `S2`;
- trust display shows `safe_summary` and `deterministic_dev`;
- trace panel shows `real_bluesky_fetch_enabled`, `dev_adapter_search_rag`, and `dev_adapter_dspy`.

## Commands Run

```bash
cd backend && uv run ruff check app && uv run mypy app && uv run pytest app/tests
npm --prefix frontend run lint && npm --prefix frontend test
make requirements-review
make deep-review
```

## Accepted Limitations

- Search/RAG is not final and is not allowed to satisfy final retrieval or citation requirements.
- DSPy is not final and is not allowed to satisfy final agent workflow requirements.
- Trust scoring is a fixed Gate 3 safe-summary trace value, not the final T14 trust module.
- The eval harness, image understanding, provider comparison, GEPA, and MLflow remain later gates.
- `R014`, `R015`, and `R045` remain planned because the Gate 3 adapter cannot close final response, citation, or no-fake-product-behavior acceptance.

## Ship Decision

Approved to ship Gate 3 after rerunning `make deep-review` with this review file included.

## Post-Review Correction

The follow-up review finding about `docs/requirements_matrix.md` row `R008` was resolved after Gate 3 shipped. `R008` now references the actual Makefile smoke targets, frontend/API files, browser-use verification, and this review record instead of a missing `scripts/user_smoke_check.py` file.
