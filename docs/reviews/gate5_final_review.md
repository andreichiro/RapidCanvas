# Gate 5 Final Review

Date: 2026-04-30  
Prepared by: Dev D  
Review target: integrated Gate 5 branch after Dev A/B/C/D/E lane outputs are merged.

## Review Rule

This is the C5 acceptance record. Do not mark final real-pipeline requirement rows implemented until this review has real evidence from the integrated branch.

C1-C4 compatibility fixtures may support lane handoffs, but they are not product acceptance.

## Checkpoint Results

| checkpoint | expected evidence | result | notes |
|---|---|---|---|
| C0 API contract freeze | Dev A schema/OpenAPI/client freeze evidence | pending | no producing-lane evidence recorded yet |
| C1 `PostContext` handoff | Dev B retrieval consumes Dev A `PostContext` without schema adapters | pending | fixture prepared |
| C2 `Evidence[]` handoff | Dev C consumes Dev B evidence, diagnostics, source ids, and warnings | pending | fixture prepared |
| C3 `ExplainerService` handoff | Dev A calls Dev C service and receives `ExplainResponse` | pending | checklist prepared |
| C4 API response handoff | Dev E renders real-shaped API response | pending | fixture prepared |
| C5 final serial spine | `/api/explain` runs the real serial spine end to end | pending | this review records the result |

## Required Product Checks

- [ ] Real Bluesky post fetch is active in `POST /api/explain`.
- [ ] Real Search/RAG returns cited evidence and retrieval diagnostics.
- [ ] Real DSPy workflow produces and validates the explanation.
- [ ] Trust/fallback behavior is computed from evidence, guardrails, and validation, not hardcoded.
- [ ] Every factual bullet has one or more source ids.
- [ ] Every cited source id exists in the response `sources` list.
- [ ] Trace includes retrieval, guardrail, trust, fallback, and adapter diagnostics.
- [ ] Temporary dev adapters are absent, or explicitly trace-marked as non-final and excluded from final requirement closure.
- [ ] Runtime keys are supplied only through local environment or ignored `.env`, never committed.
- [ ] Generated reports, `mlruns/`, Qdrant cache, and live outputs remain untracked.

## Command Evidence

Record exact command results from the integrated branch.

```bash
make setup
make lint
make test
make requirements-review
make skills-review
make check-secrets
make eval
python3 scripts/check_requirements_matrix.py
python3 scripts/quick_validate.py .codex/skills/*
make deep-review
```

## Targeted Real-Service Smokes

Run only with runtime-supplied keys where needed. Record skipped providers with reasons.

```bash
cd backend && uv run python -m app.eval.runner --mode api --judge deterministic
```

Suggested additional evidence to record:

- Public Bluesky post URL used for live fetch.
- Retrieval provider, embedding provider, vector store mode, and reranker mode.
- DSPy model/provider and whether provider calls were live or guarded fallback.
- Response summary: bullet count, source count, source ids per bullet, trust score, fallback mode, adapter mode, warnings, guardrail flags.
- Browser or frontend smoke result after Dev E verifies the real response.

## Matrix Closure Decision

Keep these rows planned unless the integrated review evidence supports closure:

| row | closure requirement |
|---|---|
| `R013` | real Search/RAG code, tests, and C5 proof |
| `R014` | real integrated 3-5 bullet behavior |
| `R015` | every factual bullet cites source ids in C5 |
| `R016` | real-pipeline usefulness and accuracy eval evidence |
| `R017` | Gate 6 real or fixture-backed public Bluesky post eval set |
| `R018` | expected outputs for the Gate 6 public eval set |
| `R024` | final real DSPy workflow code, tests, and C5 proof |
| `R025` | FastAPI route using the final real DSPy pipeline |
| `R034` | computed trust/fallback behavior proven in C5 |
| `R045` | no unmarked dev adapters in final accepted behavior |

## Review Decision

Decision: pending integration evidence.

Open lane evidence:

- Dev A:
- Dev B:
- Dev C:
- Dev E:

Known live-service limitations:

- Bluesky public read behavior can drift or fail by network/provider state.
- Bluesky search may require auth or degrade through typed sanitized errors.
- OpenAI/model/provider smokes require runtime-only credentials.
- Optional Ragas/DSPy/provider runs may be skipped only with explicit reasons.
