# RAG Eval MLflow Notes

Required metrics:
- expected-point recall
- retrieval recall at 6
- citation coverage
- Ragas-shaped faithfulness, context precision, context recall
- hallucination count and unsupported claim rate
- prompt-injection resistance
- guardrail trigger accuracy
- abstention precision and recall
- private URL block rate

Report artifacts:
- `eval_results.jsonl`
- `eval_report.md`
- `confusion_matrix.csv`
- `metric_bars.svg`
- `summary.json`

Cached eval must not call Bluesky, web search, OpenAI, DSPy, or MLflow.
