# Gate 5 Parallelization Plan

Gate 5 is the first real integration gate. It may be implemented with parallel
developer branches, but Gate 5 itself must finish before Gate 6 starts. Gate 6
may then be parallelized internally, and Gate 7 may be parallelized internally
after Gate 6 lands. Do not run Gate 5, Gate 6, and Gate 7 as independent
parallel delivery gates.

Gate 5 has one serial integration spine that every lane must preserve:

```text
real Bluesky fetch
-> real search/context documents
-> embed/retrieve/rerank
-> DSPy explain/validate
-> trust/fallback
-> API response
```

The work inside Gate 5 should be split as follows to minimize conflicts.

## Contract Checkpoints During Parallel Work

These checkpoints replace vague "mini spine" language. They are not shared
implementation sessions and they are not final acceptance. They are small
handoff tests that let each isolated lane prove its output can be consumed by
the next lane without editing the next lane's code.

Rules:

- Each developer stays inside their owned files.
- Dev D owns canonical Gate 5 fixture/review files when a shared artifact is
  needed.
- Producers publish typed fixtures or protocol functions; consumers write tests
  against those fixtures/protocols.
- A checkpoint can pass with controlled fixtures, but final Gate 5 acceptance
  still requires the full real serial spine.

Checkpoint order:

```text
C0 API contract freeze
C1 A -> B PostContext handoff
C2 B -> C Evidence handoff
C3 C -> A ExplainerService handoff
C4 A -> E API response handoff
C5 final end-to-end serial spine
```

Checkpoint details:

| checkpoint | producer | consumer | artifact or test | pass condition |
|---|---|---|---|---|
| C0 API contract freeze | Dev A | B/C/D/E | `backend/app/schemas/*`, OpenAPI, `frontend/src/api/client.ts` | request/response shape is stable enough for all lanes |
| C1 `PostContext` handoff | Dev A, with Dev D fixture help | Dev B | real/cached `PostContext` fixture plus Dev B retrieval test | Dev B retrieval accepts the object without schema adapters |
| C2 `Evidence[]` handoff | Dev B, with Dev D fixture help | Dev C | retrieval result fixture plus Dev C explainer test | Dev C consumes evidence, diagnostics, source ids, and warnings |
| C3 explainer service handoff | Dev C | Dev A | `ExplainerService` protocol/builder plus API integration test | Dev A can call the service and receive `ExplainResponse` |
| C4 API response handoff | Dev A | Dev E | real-shaped API response fixture plus frontend test | UI renders bullets, citations, sources, trust/fallback, and trace |
| C5 final serial spine | Integration branch, reviewed by Dev D | all lanes | `docs/reviews/gate5_final_review.md` | real pipeline passes end-to-end through `/api/explain` |

Practical effect:

- Dev B does not need Dev C's code to start; B only needs C1.
- Dev C does not need live retrieval to start; C can build against C2 fixtures,
  then replace them with Dev B's real service during final integration.
- Dev E does not need the final backend to start; E builds against C4 response
  fixtures, then browser-verifies the real endpoint after C5.
- Dev D does not mark requirement rows implemented from checkpoints alone.
  Only C5 can close real Search/RAG, real DSPy, real citation, and real
  trust/fallback rows.

## Dev A - API And Bluesky Integration

Owns:

```text
backend/app/api/routes.py
backend/app/deps.py
backend/app/schemas/api.py
backend/app/schemas/domain.py
backend/app/clients/bsky.py
backend/app/tests/integration/test_api_contracts.py
backend/app/tests/integration/test_gate5_real_pipeline.py
```

Scope:

- Keep `POST /api/explain`, `GET /api/health`, and `GET /api/providers` stable.
- Wire the route dependency from the Gate 3 adapter to the real Gate 5 explainer only after Dev B and Dev C expose stable service builders.
- Propagate real Bluesky fetch warnings into public trace fields.
- Preserve Dev A's real post/thread fetch, parent, quote, link, image, and unavailable-post normalization.
- Keep provider errors typed and sanitized.
- Ensure final API response validates against `ExplainResponse` with 3-5 bullets, sources, trust/fallback fields, and no unmarked dev adapters.

Must not edit:

```text
backend/app/ml/*
backend/app/clients/search.py
backend/app/clients/fetcher.py
backend/app/guardrails/*
backend/app/agent/*
backend/app/eval/*
frontend/*
```

Handoff contract:

- Dev A owns schema or route-contract changes. Any schema change must include matching frontend client, API tests, and handoff notes in the same integration window.
- Dev A performs the final route switch only on the integration branch after Dev B retrieval and Dev C explainer pass their lane tests.

## Dev B - Real Search/RAG Retrieval

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
```

May create if needed:

```text
backend/app/ml/retrieval_service.py
backend/app/tests/integration/test_gate5_retrieval.py
```

Scope:

- Expose a real retrieval service that accepts `PostContext` plus generated queries and returns sanitized `ContextDocument` and `Evidence` objects.
- Use real linked-page fetch, source sanitization, prompt-injection scanning, OpenAI embeddings, Qdrant local retrieval, reranking, and retrieval diagnostics.
- Preserve the normalized `ContextDocument` pass-through path for Dev A Bluesky search results.
- Surface retrieval warnings and guardrail flags for Dev C trust orchestration and Dev A API trace.
- Keep deterministic fake embeddings only in tests; production Gate 5 retrieval must use the configured real embedding provider unless explicitly unavailable and trace-marked as non-final.

Must not edit:

```text
backend/app/api/*
backend/app/deps.py
backend/app/schemas/*
backend/app/agent/*
backend/app/eval/*
frontend/*
```

Handoff contract:

- Dev B exposes a small typed retrieval builder/function for Dev C; Dev B does not wire it into the public route directly.
- Dev B documents any live Bluesky search limitation, fallback, or auth need without weakening direct real Bluesky post/thread fetch.

## Dev C - Real DSPy, Providers, And Guardrails

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
backend/app/agent/signatures.py
backend/app/agent/program.py
backend/app/agent/loader.py
backend/app/agent/providers.py
backend/app/agent/service.py
backend/app/tests/integration/test_gate5_explainer.py
```

Scope:

- Implement the real DSPy signatures and module path for classify, query planning, evidence reranking or selection, explanation, validation, prompt-injection risk, and trust assessment.
- Orchestrate Dev B retrieval output into cited 3-5 bullet explanations.
- Implement provider configuration for OpenAI default and optional configured providers without breaking `GET /api/providers`.
- Implement trust scoring, output guardrails, fallback modes, and one revision attempt.
- Ensure no retrieved content is treated as instructions.
- Expose a real explainer service compatible with Dev A's `ExplainerService` protocol.

Must not edit:

```text
backend/app/api/routes.py
backend/app/clients/bsky.py
backend/app/clients/search.py
backend/app/ml/*
backend/app/eval/*
frontend/*
```

Handoff contract:

- Dev C supplies `explain(request) -> ExplainResponse` or a builder returning that service; Dev A wires it into `deps.py`.
- Dev C may request schema additions from Dev A but must not change public contracts unilaterally.

## Dev D - Integration Fixtures And Requirement Closure

Owns:

```text
eval/fixtures/*
docs/current_handoff.md
docs/requirements_matrix.md
TRANSLATION_LOG.md
docs/reviews/*
backend/app/tests/fixtures/*
```

May create if needed:

```text
docs/reviews/gate5_final_review.md
eval/fixtures/gate5/*
```

Scope:

- Add integration fixtures that exercise real Bluesky fetch, real retrieval, real DSPy response shape, trace/fallback fields, and adapter-removal checks.
- Update requirement-matrix rows only when implementation files and tests exist.
- Keep rows such as real Search/RAG, real DSPy workflow, real citations, real trust/fallback, and real eval as planned until their Gate 5/6 proof exists.
- Record assumptions, live-service limitations, provider skips, and cross-lane edits in `TRANSLATION_LOG.md`.
- Prepare the Gate 5 final review template and acceptance checklist.

Must not edit:

```text
backend/app/api/*
backend/app/agent/*
backend/app/ml/*
frontend/*
```

Handoff contract:

- Dev D can prepare fixtures and docs during Gate 5, but cannot mark Gate 6 eval quality complete before the Gate 5 real pipeline lands.
- Dev D is the final owner of requirement-matrix status changes.

## Dev E - Frontend Real-Response Verification

Owns:

```text
frontend/src/*
frontend/package.json
frontend/package-lock.json
README.md UI usage sections
```

Scope:

- Verify the existing UI renders the real Gate 5 response without schema drift.
- Adjust trace/fallback display only if Dev A-approved API fields change.
- Preserve citation chips, source list, trust/fallback badge, guardrail flags, trace panel, loading, error, partial, abstain, and safe-summary states.
- Add or update frontend tests for any real-response edge states introduced by Gate 5.
- Run browser-use verification against the real local backend after Dev A/B/C integration lands.

Must not edit:

```text
backend/*
docs/requirements_matrix.md
TRANSLATION_LOG.md
```

Handoff contract:

- Dev E consumes the public API contract; backend changes must come through Dev A.
- Dev E records browser-use observations through the Gate 5 final review or handoff, not by changing backend logic.

## Merge And Review Order

Use an integration branch such as:

```text
codex/gate5-real-integration
```

Recommended merge order:

```text
1. Dev B retrieval service branch
2. Dev C real DSPy/guardrail service branch
3. Dev A route/dependency wiring branch
4. Dev D fixtures/matrix/review branch
5. Dev E frontend verification branch
```

The final Gate 5 review must prove:

```text
real Bluesky post fetch is active
real Search/RAG retrieves cited evidence
real DSPy workflow produces and validates the explanation
trust/fallback behavior is real, not a fixed dev-adapter value
every factual bullet has source ids
trace includes retrieval, guardrail, trust, and fallback diagnostics
temporary dev adapters are absent, or explicitly trace-marked as non-final and
not counted as closing final requirement rows
make deep-review passes
targeted real-service smoke tests pass with environment keys supplied only at runtime
```
