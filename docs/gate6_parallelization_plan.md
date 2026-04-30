# Gate 6 Parallelization Plan

Gate 6 is the quality layer. It starts only after Gate 5 lands a real integrated
pipeline. Gate 6 may be implemented with parallel developer branches, but those
branches must all measure the real Gate 5 pipeline, not the Gate 3 deterministic
adapter. Gate 7 starts only after Gate 6 lands.

Gate 6 has one serial quality spine that every lane must preserve:

```text
real Gate 5 pipeline
-> cached/live eval inputs
-> production error taxonomy
-> Ragas and custom judge metrics
-> prompt-injection and low-trust attack suites
-> confusion matrices and graphs
-> MLflow run with artifacts
-> Gate 6 review decision
```

The work inside Gate 6 should be split as follows to minimize conflicts.

## Dev A - API Contract And Eval Smoke Stability

Owns:

```text
backend/app/api/routes.py
backend/app/deps.py
backend/app/schemas/api.py
backend/app/schemas/domain.py
backend/app/tests/integration/test_api_contracts.py
backend/app/tests/integration/test_gate6_api_eval_smoke.py
```

Scope:

- Keep the public API stable while Gate 6 eval tooling exercises it repeatedly.
- Add integration smoke coverage that calls the real Gate 5 `/api/explain` path with cached or controlled inputs.
- Ensure trace fields needed by metrics remain present: warnings, trust score, fallback mode, guardrail flags, adapter mode, and source ids.
- Preserve clear API failures for invalid, unavailable, deleted, or upstream-failed Bluesky posts.
- Verify no Gate 6 eval path introduces write-capable external API behavior.

Must not edit:

```text
backend/app/eval/*
backend/app/ml/*
backend/app/agent/*
frontend/*
eval/*
reports/*
```

Handoff contract:

- Dev A owns only API contract stability and smokeability. Dev D owns eval semantics and metric status.
- Any public schema change must be coordinated with Dev E and reflected in eval fixtures before merge.

## Dev B - Retrieval Metrics And Source-Safety Evidence

Owns:

```text
backend/app/clients/search.py
backend/app/clients/fetcher.py
backend/app/clients/extraction.py
backend/app/ml/diagnostics.py
backend/app/ml/embeddings.py
backend/app/ml/vector_store.py
backend/app/ml/rerankers.py
backend/app/guardrails/prompt_injection.py
backend/app/tests/unit/test_search.py
backend/app/tests/unit/test_fetcher.py
backend/app/tests/unit/test_rag.py
backend/app/tests/unit/test_prompt_injection.py
backend/app/tests/integration/test_gate6_retrieval_metrics.py
```

May create if needed:

```text
backend/app/ml/retrieval_metrics.py
backend/app/tests/fixtures/retrieval/*
```

Scope:

- Expose retrieval diagnostics needed by Gate 6 metrics: retrieval recall@6 inputs, source ids, scores, source-channel coverage, prompt-injection flags, sanitization warnings, and private URL block evidence.
- Add tests for retrieval recall inputs, Qdrant retrieval behavior, source diversity, sanitizer behavior, and unsafe/private URL blocking.
- Ensure cached fixture mode can replay retrieval-related evidence without requiring live network access.
- Preserve real OpenAI/Qdrant paths for live eval while keeping deterministic fake embeddings only for unit tests.

Must not edit:

```text
backend/app/api/*
backend/app/deps.py
backend/app/schemas/*
backend/app/agent/*
backend/app/eval/*
frontend/*
reports/*
```

Handoff contract:

- Dev B supplies typed retrieval diagnostics for Dev D metrics; Dev B does not decide final eval scores.
- Dev B documents live-service limitations as warnings/evidence, not as passing metrics.

## Dev C - Agent, Guardrail, Judge Support, And MLflow Substrate

Owns:

```text
backend/app/agent/*
backend/app/guardrails/trust.py
backend/app/guardrails/output.py
backend/app/guardrails/policies.py
backend/app/ops/mlflow.py
backend/app/tests/unit/test_agent*.py
backend/app/tests/unit/test_guardrails.py
backend/app/tests/unit/test_mlflow*.py
```

May create if needed:

```text
backend/app/agent/eval_support.py
backend/app/agent/judge_signatures.py
backend/app/tests/integration/test_gate6_agent_quality_hooks.py
```

Scope:

- Ensure the real DSPy program emits enough structured trace data for Gate 6 metrics without exposing chain-of-thought.
- Provide guardrail outputs required by eval: unsupported-claim detection, fallback correctness, prompt-injection resistance, source-support validation, and abstention reasons.
- Provide MLflow helpers that Dev D can call to log params, metrics, artifacts, provider comparisons, and model metadata.
- Keep LLM judge prompt/signature support structured and reusable; Dev D owns the eval runner that invokes it.
- Ensure provider choice, latency, and cost metadata can be reported without leaking secrets.

Must not edit:

```text
backend/app/api/*
backend/app/clients/*
backend/app/ml/*
backend/app/eval/runner.py
backend/app/eval/report.py
frontend/*
eval/posts.yaml
reports/*
```

Handoff contract:

- Dev C supplies structured agent/guardrail/MLflow hooks. Dev D owns metric aggregation and reports.
- Dev C must not mark eval rows complete unless Dev D's eval artifacts exist and pass.

## Dev D - Eval Harness, Metrics, Reports, And Requirement Closure

Owns:

```text
eval/posts.yaml
eval/fixtures/*
eval/fixtures/prompt_injection/*
backend/app/eval/dataset.py
backend/app/eval/metrics.py
backend/app/eval/judge.py
backend/app/eval/runner.py
backend/app/eval/report.py
docs/requirements_matrix.md
docs/current_handoff.md
TRANSLATION_LOG.md
docs/reviews/*
reports/.gitkeep
```

May create if needed:

```text
docs/reviews/gate6_final_review.md
reports/gate6/.gitkeep
backend/app/tests/unit/test_eval*.py
backend/app/tests/integration/test_gate6_eval_runner.py
```

Scope:

- Implement `eval/posts.yaml` with 12+ cases and expected outputs, including niche, meme, news, reply, quote, link, image, ambiguous, adversarial, sparse, non-English, unavailable/deleted, prompt-injection, contradictory, and low-evidence cases.
- Implement cached fixture mode as the default and live refresh as an explicit command only.
- Implement deterministic metrics: goal understanding, tool choice, tool use, requirement following, sequence validity, recovery, hallucination count, irreversible-action safety, final response correctness, expected-point recall, retrieval recall@6, citation coverage, latency p50/p95, prompt-injection resistance, guardrail trigger accuracy, abstention precision/recall, unsupported claim rate, unsafe output rate, source quote leakage rate, and private URL block rate.
- Integrate Ragas metrics and the custom DSPy/LLM judge support supplied by Dev C.
- Generate JSONL, Markdown, confusion matrices, and graph artifacts.
- Update requirement-matrix statuses only when code, tests, eval artifacts, and docs are present.
- Write the Gate 6 final review record.

Must not edit:

```text
backend/app/api/*
backend/app/clients/*
backend/app/ml/*
backend/app/agent/*
frontend/*
```

Handoff contract:

- Dev D is the final owner of Gate 6 metric definitions, report semantics, requirement-matrix closure, and review record.
- Dev D must keep generated live reports out of Git unless a small placeholder or curated artifact is explicitly intended.

## Dev E - Frontend Quality Verification And User-Style Evidence

Owns:

```text
frontend/src/*
frontend/package.json
frontend/package-lock.json
README.md UI usage sections
```

May create if needed:

```text
frontend/src/components/EvalStatusBadge.tsx
frontend/src/components/QualityTraceSummary.tsx
```

Scope:

- Verify the UI remains stable while Gate 6 runs real eval and attack cases through the backend.
- Add frontend tests for user-visible low-trust, abstain, partial, prompt-injection warning, contradictory-source warning, and citation/source rendering states if the Gate 5 response adds or tightens fields.
- Run browser-use verification against representative Gate 6 cases: normal explanation, partial fallback, abstain fallback, prompt-injection flag, and unavailable/deleted post error.
- Keep frontend changes limited to displaying existing public API fields; do not create separate frontend-only quality logic.

Must not edit:

```text
backend/*
docs/requirements_matrix.md
TRANSLATION_LOG.md
eval/*
reports/*
```

Handoff contract:

- Dev E consumes Dev A's public API shape and Dev D's selected smoke cases.
- Dev E records browser-use observations through the Gate 6 final review or README UI usage notes.

## Merge And Review Order

Use an integration branch such as:

```text
codex/gate6-quality-layer
```

Recommended merge order:

```text
1. Dev A API eval-smoke stability branch
2. Dev B retrieval diagnostics/metric-support branch
3. Dev C guardrail/judge/MLflow-support branch
4. Dev D eval runner, metrics, reports, and requirement matrix branch
5. Dev E frontend quality-verification branch
```

The final Gate 6 review must prove:

```text
Gate 5 real pipeline is the measured target
cached eval runs 12+ cases with expected outputs
at least 10 cached cases run without network
Ragas metrics run or skip with explicit documented reason
custom production-error metrics run
prompt-injection attack fixtures run
low-trust and contradictory-source fixtures run
confusion matrices and graphs are generated
MLflow logs params, metrics, artifacts, and model/package metadata
unsupported factual claim rate is measured
private/local URL blocking is measured
make deep-review passes
make eval passes
make mlflow-log passes or is explicitly blocked with a documented environment reason
requirement matrix has no unmapped rows and no premature implemented statuses
```
