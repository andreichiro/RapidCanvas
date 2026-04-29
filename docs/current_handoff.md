# Current Handoff

Updated: 2026-04-29  
Repository: `andreichiro/RapidCanvas`  
Shared branch: `main`  
Dev A remote branch: `codex/dev-a-gate4`
Dev B isolated branch: `codex/dev-b-gate4-retrieval-safety`

## Current State

- Gate 0 is implemented: scaffold, command surface, secret hygiene, backend health route, React shell, tests, and deep review workflow.
- Gate 1 is implemented: `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement, and `make requirements-review` enforces 45 rows.
- Gate 2 is implemented: FastAPI/domain contracts are frozen in `backend/app/schemas/`, `backend/app/api/routes.py`, and `backend/app/deps.py`.
- Gate 3 is implemented: `/api/explain` performs real Bluesky post/thread fetching and returns a schema-valid cited safe summary.
- Dev A Gate 4 has shipped remotely on `github/codex/dev-a-gate4` at `080900d`; it expands Backend/API/Bluesky normalization and adds a read-only Bluesky `search_posts()` wrapper.
- Dev B Gate 4 lane is implemented in the isolated clone at `/Users/akatsurada/Documents/New-project-dev-b-gate4`.
- Dev B added real Search/RAG/source-safety modules, but the live `/api/explain` route still uses the Gate 3 adapter until Dev A/C integration replaces the route builder.
- DSPy is still a deterministic dev adapter and every Gate 3 response marks this in `trace`.
- `R045` is partially exercised by Gate 3 adapter tracing but remains planned for final real-pipeline enforcement.
- Post-review Gate 3 matrix fix is applied: `R008` now points to actual smoke/browser verification files and commands.

## Dev B Gate 4 Lane

Implementation root:

```text
/Users/akatsurada/Documents/New-project-dev-b-gate4
```

Branch:

```text
codex/dev-b-gate4-retrieval-safety
```

Added Dev B-owned behavior:

- Search provider protocols and adapters in `backend/app/clients/search.py`.
- DDGS-backed web search and read-only Bluesky search normalization.
- Safe linked-page fetcher in `backend/app/clients/fetcher.py`.
- HTML/text extraction helper in `backend/app/clients/extraction.py`.
- SSRF/private-IP/localhost/link-local/file-scheme blocking before fetch and before redirects.
- Prompt-injection scanning and source sanitization in `backend/app/guardrails/prompt_injection.py`.
- OpenAI embedding wrapper with diskcache plus deterministic test embeddings in `backend/app/ml/embeddings.py`.
- Chunking variants, in-memory vector store, Qdrant local-mode store, and `RagService.retrieve()` in `backend/app/ml/vector_store.py`.
- Retrieval diagnostics in `backend/app/ml/diagnostics.py`, including prompt-injection flags/warnings surfaced through `RagService.last_diagnostics`.
- Similarity, optional HF cross-encoder, and optional DSPy rerankers in `backend/app/ml/rerankers.py`; optional HF setup now falls back if model loading fails.
- Unit tests for search, safe fetch, prompt-injection scanning, RAG retrieval, Qdrant optional behavior, and reranker fallback.

Important integration notes:

- Dev B was compared against Dev A remote branch `github/codex/dev-a-gate4` before shipping.
- Backend implementation ownership is disjoint: Dev A changed API/Bluesky/schema/test files, while Dev B added retrieval/source-safety modules.
- Merge overlap exists in `docs/current_handoff.md`, `TRANSLATION_LOG.md`, `scripts/verify_lane_isolation.sh`, and `scripts/assert_lane_execution_context.sh`; preserve both lanes' handoff entries during integration.
- Dev B's generic isolation verifier is stricter about standalone clones and exact shared worktree ownership checks; Dev B's context guard now also accepts execution from subdirectories under the approved execution root, matching Dev A's useful behavior.
- Dev A's `BlueskyClient.search_posts()` and `PostContext.warnings` should be preserved. Dev B's `BlueskySearchProvider` can consume or wrap Dev A's read-only Bluesky search during the integration window.
- Dev B did not change frozen API/domain schemas.
- Dev B did not wire Search/RAG into `/api/explain`; that integration belongs to the Dev A/C merge window.
- `RagService.retrieve(query, documents) -> Evidence[]` is ready for integration and exposes prompt-injection diagnostics through `last_diagnostics`.
- Optional Qdrant and web extraction paths were verified with extras, not only the base dev environment.

## Verified Commands

Run this before any handoff, commit, or push:

```bash
make deep-review
```

The current passing gate covers linting, typing, backend tests, frontend tests, secret scan, config validation, frontend audit/build, optional backend dependency dry-run, requirement matrix validation, generated artifact cleanup, maintainability review, and user smoke checks.

Additional Dev B Gate 4 checks performed before handoff:

```text
scripts/verify_dev_B_gate4_isolation.sh
scripts/assert_dev_B_gate4_execution_context.sh
uv run ruff check app && uv run mypy app
uv run pytest app/tests/unit/test_search.py app/tests/unit/test_rag.py
uv run --extra bluesky pytest app/tests/unit/test_fetcher.py app/tests/unit/test_search.py
uv run --extra ai pytest app/tests/unit/test_rag.py::test_qdrant_vector_store_recreate_and_query_when_dependency_available
make deep-review
git fetch github --prune
git diff --name-status github/main..github/codex/dev-a-gate4
git diff --name-status github/main..codex/dev-b-gate4-retrieval-safety
```

All Dev B checks above passed in the isolated clone.

Additional Gate 3 user-style checks performed before handoff:

```text
POST /api/explain with https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y
browser-use verification at http://127.0.0.1:5174/
```

Both checks confirmed real Bluesky fetch, 3 cited bullets, `fallback_mode=safe_summary`, `adapter_mode=deterministic_dev`, and visible adapter guardrail flags.

Review follow-up:

```text
R008 no longer references a missing scripts/user_smoke_check.py file.
```

## Important Boundaries

- Do not replace the trace-marked Gate 3 adapter with unmarked fake explanation bullets.
- Do not claim integrated `/api/explain` Search/RAG, DSPy, eval, full guardrails, image understanding, provider comparison, GEPA, or MLflow are complete until their real files, tests, eval artifacts, and matrix rows are updated.
- Real Bluesky post fetch is required for future integration gates.
- Temporary deterministic dev adapters may be used only while real Search/RAG or DSPy modules are incomplete.
- Any dev adapter use must be visible in `trace`.
- Dev adapters cannot satisfy final acceptance or requirement-matrix rows.
- Shared `/Users/akatsurada/Documents/New project` remained inspection-only for Dev B lane work.
- Do not merge Dev B by overwriting Dev A's `docs/current_handoff.md` or `TRANSLATION_LOG.md`; combine the lane sections additively.

## Next Work

Recommended next step: merge Dev A and Dev B through normal review, preserving both lanes' code and handoff notes, then integrate Dev B Search/RAG with Dev A/C service wiring while Dev D keeps the T1 handoff spine/research deliverables moving.

Expected additions:

- `docs/research/*.md`
- `.codex/skills/*`
- `docs/task_packets.md`
- updated `AGENTS.md`, `README.md`, `TRANSLATION_LOG.md`, and `docs/requirements_matrix.md`

During the integration window, replace deterministic adapters with real Search/RAG and DSPy modules while preserving the no-fake-product-behavior rule.

## Review Records

- `docs/reviews/gate1_final_review.md`
- `docs/reviews/gate2_final_review.md`
- `docs/reviews/gate3_final_review.md`
