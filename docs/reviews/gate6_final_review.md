# Gate 6 Final Review

Date: 2026-05-01
Branch: `codex/dev-d-gate6-eval-reports`
Baseline: Dev A Gate 6 API smoke baseline `57aefac`

## Scope

Dev D produced the Gate 6 truth-layer package: cached eval cases, metric
aggregation, report artifacts, requirement-matrix honesty, final review notes,
and handoff updates. This lane did not edit API routing, retrieval runtime,
DSPy runtime, guardrail runtime, MLflow internals, or frontend code.

## Decision

QD passes for Dev D. The required commands listed below pass, and the default
quality report is deterministic and honest: it evaluates cached fixture-backed
Gate 5 response shapes, distinguishes public Bluesky fixture coverage from
synthetic attack fixtures, and records optional-tool skips instead of hiding
them.

## Evidence Package

| Check | Result |
|---|---|
| Gate 5 real integration present | Present on the baseline through Dev A smoke stability: the service builds `AgentExplainerService` with Dev B `RetrievalEvidenceRetriever`; no-key/provider downgrades remain trace-visible. |
| 12+ eval cases | Passed: 19 cases in `eval/posts.yaml`. |
| 10+ cached cases without network | Passed: 19 cached fixture rows. |
| Public Bluesky fixture coverage | Passed for fixture-backed coverage: 10 public Bluesky URLs verified by read-only AppView calls on 2026-05-01. |
| Synthetic cases marked | Passed: 9 `synthetic_fixture` rows remain for prompt-injection, private URL, unavailable/deleted, contradiction, false premise, low evidence, and non-English coverage. |
| Attack fixture manifest | Passed: raw prompt-injection/private URL payloads are inventoried in `eval/fixtures/prompt_injection/manifest.json` and checked against cached attack rows. |
| Core metrics | Passed: expected-point recall, citation coverage, unsupported/hallucination count, fallback correctness, prompt-injection resistance, private URL block rate, latency p50/p95, and production taxonomy metrics. |
| Report artifacts | Passed: JSONL, Markdown, summary JSON, confusion matrix CSV, and SVG metric graph are generated under ignored `reports/eval/`. |
| Explicit API-mode eval | Completed as a live-route smoke, but the local no-credential setup abstained on all 19 rows; this is recorded as a limitation, not final live quality closure. |
| Ragas / DSPy judge | Default `make eval` skips both with explicit reasons; explicit offline DSPy, Ragas, and composite judge commands ran after `make setup`. |
| Automated readiness review | Passed: `test_gate6_eval_readiness.py` checks case mix, public/synthetic provenance, raw attack-fixture manifest parity, API-shaped fixtures, source/citation references, report artifacts, optional-tool labels, and no synthetic public coverage. |
| MLflow | Kept out of default eval; explicit `make mlflow-log` ran and created local ignored run `7a2d704cf7304735bb725ed3926b66e9`; `make deep-review` cleans `backend/mlruns/`. |
| Requirement matrix | Updated with no unmapped rows and no synthetic cases counted as public coverage. |
| Generated artifacts | `reports/*`, `mlruns/`, Qdrant/cache output, `.env`, and live outputs remain ignored. |

## Default Eval Snapshot

`make eval` produced:

```text
case_count=19
public_fixture_case_count=10
public_bluesky_fixture_case_count=10
synthetic_fixture_case_count=9
ragas_metric_source=deterministic_proxy
expected_point_recall=1.000
citation_coverage=1.000
final_response_correctness=1.000
fallback_correctness=1.000
hallucination_count=0.000
unsupported_claim_rate=0.000
prompt_injection_resistance=1.000
private_url_block_rate=1.000
latency_p50=55.0
latency_p95=77.0
```

These scores are cached-fixture scores, not proof that every current live public
post will produce the same output under provider-backed runtime conditions.

## API-Mode Smoke Snapshot

An explicit API-mode eval was run after the cached report:

```text
prediction_mode=api
live_case_count=19
fallback_modes={"abstain": 19}
expected_point_recall=0.228
citation_coverage=0.526
final_response_correctness=0.158
unsupported_claim_rate=0.474
prompt_injection_resistance=0.842
private_url_block_rate=0.947
```

This proves the eval runner can score the wired FastAPI route without aborting,
but it also shows the local no-credential/live-service posture is not enough to
claim final live-route quality. The default submission evidence remains the
deterministic cached report, and release review should rerun selected public
cases with runtime credentials before treating API-mode scores as final.

## Remaining Gate 7 / Integration Work

- Run selected public cases through explicit API mode with runtime credentials
  and live service access when release-captain integration is ready.
- Use Dev E browser verification against representative Gate 6 cases: normal,
  partial fallback, safe summary, prompt-injection flag, and unavailable/deleted
  error.
- Keep image understanding and provider comparison rows reserved until their
  final runtime/browser evidence exists.
- Do not commit generated report directories, `mlruns/`, `.env`, Qdrant cache,
  or live output.

## Commands Run

```text
scripts/verify_dev_D_gate6_isolation.sh
scripts/assert_dev_D_gate6_execution_context.sh
make setup
cd backend && uv run pytest app/tests/unit/test_eval_dataset.py app/tests/unit/test_eval_metrics.py app/tests/unit/test_eval_runner.py app/tests/unit/test_eval_judge.py app/tests/integration/test_gate6_eval_runner.py app/tests/integration/test_gate6_eval_readiness.py -q
make eval
cd backend && uv run --extra ai python -m app.eval.runner --mode cached --judge dspy --out reports/eval_dspy
cd backend && uv run --extra eval python -m app.eval.runner --mode cached --judge ragas --out reports/eval_ragas
cd backend && uv run --all-extras python -m app.eval.runner --mode cached --judge composite --out reports/eval_composite_final
cd backend && uv run python -m app.eval.runner --mode api --judge deterministic --out reports/eval_api_final
make mlflow-log
python3 scripts/check_gate6_shipping_audit.py
make gate6-shipping-audit
make lint
make test
make requirements-review
make check-secrets
python3 scripts/check_requirements_matrix.py
python3 scripts/quick_validate.py .codex/skills/*
make optimize
make deep-review
make eval
make check-secrets
```
