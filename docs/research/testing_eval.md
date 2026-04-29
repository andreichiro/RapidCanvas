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

## Rejected alternatives
- Do not refresh live fixtures during normal `make eval`.
- Do not let model calls be required for unit tests.
- Do not let generated reports be tracked; `reports/*` remains ignored.

## Implementation consequence
Gate 4 Dev D implements the offline runner first. Later live/provider/MLflow lanes can reuse the same case IDs, metrics, and report shapes.

