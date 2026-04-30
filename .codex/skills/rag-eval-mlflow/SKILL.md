---
name: rag-eval-mlflow
description: Evaluate RapidCanvas retrieval, citations, guardrails, provider runs, GEPA outputs, and MLflow artifacts. Use when Codex is implementing cached eval cases, deterministic metrics, Ragas/DSPy judge metrics, report generation, provider comparison reports, or MLflow logging for the Bluesky explainer.
---

# RAG Eval MLflow

## Cached Eval Workflow
1. Load cases from `eval/posts.yaml`.
2. Resolve committed fixtures under `eval/fixtures/`.
3. Score expected-point recall, retrieval recall at 6, citation coverage, Ragas-shaped metrics, production error taxonomy, prompt-injection resistance, and fallback correctness.
4. Write ignored artifacts under `reports/eval/`: JSONL, Markdown, confusion matrix CSV, SVG graph, and summary JSON.
5. Keep live refresh explicit and outside the default eval command.

## MLflow Workflow
1. Set tracking URI from settings.
2. Log params for provider, models, chunk config, reranker, dataset hash, vision flag, and guardrail policy version.
3. Log eval metrics and report artifacts.
4. Log the final DSPy package with `mlflow.dspy.log_model` when Dev C owns the final program.

## Reference
Load `references/rag_eval_mlflow.md` for metrics and artifact names.
