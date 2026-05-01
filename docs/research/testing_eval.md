# Testing And Evaluation Research

## Source links
- Pytest docs: https://docs.pytest.org/
- respx docs: https://lundberg.github.io/respx/
- Ragas metrics: https://docs.ragas.io/en/stable/concepts/metrics/
- scikit-learn confusion matrix: https://scikit-learn.org/stable/modules/generated/sklearn.metrics.confusion_matrix.html
- MLflow tracking: https://mlflow.org/docs/latest/ml/tracking/

## Exact syntax snippets
```bash
make eval
make eval-cached
cd backend && uv run pytest app/tests
cd backend && uv run python -m app.eval.runner --mode fake-agent --judge deterministic
cd backend && uv run python -m app.eval.runner --mode api --cache-policy exact-post --parallelism 4 --require-live-key --judge deterministic
cd backend && uv run --extra ai python -m app.eval.runner --mode cached --judge dspy
cd backend && uv run --extra eval python -m app.eval.runner --mode cached --judge ragas
```

```python
rows = [score_case(case, fixture) for case, fixture in cached_cases]
summary = aggregate_scores(rows)
write_reports(rows, summary, output_dir)
```

## Selected default
- `make eval` is the first-class live FastAPI quality path. It requires
  `OPENAI_API_KEY`, scores the current `/api/explain` runtime with bounded
  retrieval limits and parallel case execution, and may fall back to cached
  output only when the cached prediction URL exactly matches the case.
- `make eval-cached` is the reproducible no-network path.
- `eval/posts.yaml` is JSON-compatible YAML to avoid an extra parser dependency in the default test path.
- Gate 6 cached eval includes 10 fixture-backed
  public Bluesky URLs plus synthetic attack and edge fixtures. Synthetic
  `example.com` URLs are explicitly marked and do not count toward public-post
  coverage.
- Reports include JSONL rows, Markdown summary, confusion matrix CSV, SVG metric graph, and summary JSON.
- Reports record prediction mode, judge backend, cached/live row counts, and
  whether API or model judge calls were allowed, so API/provider-backed runs are
  not mislabeled as offline cached reports.
- Gate 6 readiness tests check public/synthetic provenance, API-shaped fixture
  posts, citation references, required metric keys, and report artifacts.
- The runner accepts an `EvalAgent` protocol so cached fixtures, fake agents, and the current FastAPI app can be evaluated through the same scoring path.
- DSPy and Ragas judge backends are selectable and executable in local review:
  DSPy uses a configured provider LM when `OPENAI_API_KEY` is present and a
  no-network DSPy `BaseLM` otherwise; Ragas uses `ragas.evaluate` with LLM
  metrics when configured and non-LLM context metrics without a key. The
  deterministic judge remains the reproducible default. Numeric judge fields are
  aggregated into report summaries rather than only left in JSONL rows.

## Rejected alternatives
- Do not refresh fixture files during normal `make eval`.
- Do not let model calls be required for unit tests.
- Do not let a cached prediction for one post stand in for a different live post.
- Do not let generated reports be tracked; `reports/*` remains ignored.

## Implementation consequence
Gate 6 Dev D implements offline, fake-agent, and API runner paths plus selectable
judge backends. Gate 7 promotes the API runner to the default `make eval`
quality path and keeps `make eval-cached` for reproducible audits. API-mode
per-case failures become scored `api_eval_error` rows instead of aborting the
run, or exact-post cached rows when the cache policy proves the fixture URL is
the same post. Reports include public/synthetic fixture provenance, Ragas metric
source labeling, optional-tool skip reasons, latency summaries, fallback
correctness, and generated JSONL/Markdown/summary/confusion/SVG artifacts.
