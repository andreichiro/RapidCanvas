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
cd backend && uv run pytest app/tests
cd backend && uv run python -m app.eval.runner --mode fake-agent --judge deterministic
cd backend && uv run python -m app.eval.runner --mode api --judge deterministic
cd backend && uv run --extra ai python -m app.eval.runner --mode cached --judge dspy
cd backend && uv run --extra eval python -m app.eval.runner --mode cached --judge ragas
```

```python
rows = [score_case(case, fixture) for case, fixture in cached_cases]
summary = aggregate_scores(rows)
write_reports(rows, summary, output_dir)
```

## Selected default
- Cached eval is the default and requires no network.
- `eval/posts.yaml` is JSON-compatible YAML to avoid an extra parser dependency in the default test path.
- Reports include JSONL rows, Markdown summary, confusion matrix CSV, SVG metric graph, and summary JSON.
- Reports record prediction mode, judge backend, cached/live row counts, and
  whether API or model judge calls were allowed, so API/provider-backed runs are
  not mislabeled as offline cached reports.
- The runner accepts an `EvalAgent` protocol so cached fixtures, fake agents, and the current FastAPI app can be evaluated through the same scoring path.
- DSPy and Ragas judge backends are selectable and executable in local review:
  DSPy uses a configured provider LM when `OPENAI_API_KEY` is present and a
  no-network DSPy `BaseLM` otherwise; Ragas uses `ragas.evaluate` with LLM
  metrics when configured and non-LLM context metrics without a key. The
  deterministic judge remains the reproducible default. Numeric judge fields are
  aggregated into report summaries rather than only left in JSONL rows.

## Rejected alternatives
- Do not refresh live fixtures during normal `make eval`.
- Do not let model calls be required for unit tests.
- Do not silently run live API or model judges from default `make eval`.
- Do not let generated reports be tracked; `reports/*` remains ignored.

## Implementation consequence
Gate 4 Dev D implements offline, fake-agent, and explicit API runner paths plus selectable judge backends. API-mode per-case failures become scored `api_eval_error` rows instead of aborting the run. Later provider and MLflow lanes can reuse the same case IDs, metrics, and report shapes, while provider-backed judge runs can be enabled by setting `OPENAI_API_KEY`.
