# Gate 4 Task Packets

## Dev A - API And Bluesky
- Owner: Dev A.
- Files: `backend/app/api/`, `backend/app/clients/bsky.py`, `backend/app/schemas/`.
- Steps: preserve frozen API contracts, expand Bluesky normalization, surface warnings through trace.
- Tests: URL parsing, handle and DID resolution, thread/quote/link/image fixtures, API error mapping.
- Done: `BlueskyClient.fetch_context(url)` returns complete `PostContext` from public reads.

## Dev B - Search, Fetch, RAG, Source Safety
- Owner: Dev B.
- Files: `backend/app/clients/search.py`, `backend/app/clients/fetcher.py`, `backend/app/ml/`, `backend/app/guardrails/prompt_injection.py`.
- Steps: implement read-only search providers, safe web fetch, sanitization, embeddings, Qdrant retrieval, reranking.
- Tests: fake embeddings, chunk overlap, Qdrant idempotence, private URL blocks, prompt-injection scans.
- Done: `RagService.retrieve(query, documents)` returns cited evidence and trace warnings.

## Dev C - DSPy, Guardrails, GEPA, MLflow
- Owner: Dev C.
- Files: `backend/app/agent/`, `backend/app/guardrails/trust.py`, `backend/app/guardrails/output.py`, `backend/app/ops/mlflow.py`, `backend/app/eval/optimize.py`.
- Steps: implement DSPy signatures/modules, trust assessment, output validation, optimized loader, MLflow logging.
- Tests: mocked signatures, fallback paths, one revision attempt, optimizer dry-run, MLflow artifact run.
- Done: final agent returns exactly 3-5 cited bullets or a safe fallback with trace fields.

## Dev D - Eval, Reports, Docs, Skills
- Owner: Dev D.
- Files: `eval/posts.yaml`, `eval/fixtures/`, `backend/app/eval/`, `backend/app/tests/unit/test_eval*.py`, `docs/`, `.codex/skills/`, `AGENTS.md`, `TRANSLATION_LOG.md`.
- Steps: maintain research docs, eval dataset, deterministic metrics, report writers, prompt-injection fixtures, local skills, and matrix coverage.
- Tests: dataset validation, metric examples, cached eval smoke, skill validation, requirements review.
- Done: `make eval` emits JSONL, Markdown, confusion matrix, graph, and summary reports in ignored `reports/eval/`.

## Dev E - Frontend
- Owner: Dev E.
- Files: `frontend/` and README UI usage notes.
- Steps: implement URL form, provider selector, cited bullet rendering, source list, trust/fallback display, guardrail flags, trace panel, error/loading states.
- Tests: Vitest submit/success/error/trace/fallback cases and browser-use local verification.
- Done: the app at `http://localhost:5173` explains a Bluesky URL through the backend contract.

## Merge Order
1. Dev D eval/docs land first to make acceptance visible.
2. Dev A and Dev B land API/retrieval behavior behind existing contracts.
3. Dev C replaces deterministic adapters with DSPy/guardrails and logs eval artifacts.
4. Dev E aligns UI with the final trace/source fields.
5. Run `make deep-review`, `make eval`, and the final secret scan before submission.

