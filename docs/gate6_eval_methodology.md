# Gate 6 Eval Methodology

Gate 6 makes `make eval` the deterministic reviewer-facing quality report for
the Gate 5 pipeline contract. The default run is intentionally cached and
offline: it does not refetch Bluesky posts, call web search, call provider
models, or create MLflow runs.

## Dataset

- `eval/posts.yaml` contains 19 cases.
- 10 cases are fixture-backed public Bluesky URLs verified on 2026-05-01 with
  read-only public AppView calls.
- 9 cases are synthetic fixtures for attacks and edge cases that are difficult
  or inappropriate to source from live public posts.
- Synthetic `example.com` Bluesky URLs are explicitly marked
  `synthetic_fixture` and do not count toward public-post coverage.
- Public fixture metadata is recorded in
  `eval/fixtures/gate6_live_manifest.json`.
- `backend/app/tests/integration/test_gate6_eval_readiness.py` automatically
  checks the case mix, public/synthetic provenance, fixture API shape, citation
  references, source-object shape, optional-tool labels, and report-summary
  honesty fields.

## Default Metrics

`make eval` reports expected-point recall, final response correctness, citation
coverage, hallucination/unsupported-claim counts, fallback correctness,
prompt-injection resistance, private/local URL block rate, latency p50/p95, and
the production-error taxonomy metrics already used by the harness.

## Artifacts

The default run writes ignored artifacts under `reports/eval/`:

- `eval_results.jsonl`
- `eval_report.md`
- `summary.json`
- `confusion_matrix.csv`
- `metric_bars.svg`

These artifacts are generated for review and are not committed.

## Optional Judges And MLflow

The default run records explicit skip reasons for optional Ragas, DSPy judge,
and MLflow paths. Ragas-shaped deterministic scores are labeled
`ragas_metric_source=deterministic_proxy`; explicit Ragas runs report
`ragas_metric_source=ragas_judge`. Use explicit commands when validating those
integrations:

```bash
cd backend && uv run --extra ai python -m app.eval.runner --mode cached --judge dspy --out reports/eval_dspy
cd backend && uv run --extra eval python -m app.eval.runner --mode cached --judge ragas --out reports/eval_ragas
make mlflow-log
```

`make mlflow-log` is separate so the deterministic eval path remains offline
and does not create `mlruns/` during normal review.
