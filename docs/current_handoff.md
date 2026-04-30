# Current Handoff

Updated: 2026-04-29
Repository: `andreichiro/RapidCanvas`
Current branch: `main`
Merged Gate 4 lanes: `codex/dev-a-gate4`, `codex/dev-b-gate4-retrieval-safety`

## Current State

- Gate 0 is implemented: scaffold, command surface, secret hygiene, backend health route, React shell, tests, and deep review workflow.
- Gate 1 is implemented: `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement, and `make requirements-review` enforces 45 rows.
- Gate 2 is implemented: FastAPI/domain contracts are frozen in `backend/app/schemas/`, `backend/app/api/routes.py`, and `backend/app/deps.py`.
- Gate 3 is implemented: `/api/explain` performs real Bluesky post/thread fetching and returns a schema-valid cited safe summary.
- Gate 4 Dev A is merged into `main`: Backend/API/Bluesky normalization covers URL parsing, DID/handle AT URI construction, real thread fetch, parent context, quote text, external links, image alt text/fullsize/thumb URLs, unavailable/blocked warnings, concise upstream error wrapping, and a read-only Bluesky `search_posts()` wrapper returning `ContextDocument` objects.
- Gate 4 Dev B is merged into `main`: Search/RAG/source-safety modules cover web and Bluesky search adapters, safe linked-page fetching, prompt-injection scanning, sanitization, embeddings, Qdrant/in-memory retrieval, retrieval diagnostics, and reranking.
- The live `/api/explain` route still uses the Gate 3 trace-marked adapter until Dev A/C integration replaces the route builder and wires Dev B retrieval plus Dev C DSPy/guardrails.
- DSPy is still a deterministic dev adapter and every Gate 3 response marks this in `trace`.
- `R045` is partially exercised by Gate 3 adapter tracing but remains planned for final real-pipeline enforcement.
- Post-review Gate 3 matrix fix is applied: `R008` now points to actual smoke/browser verification files and commands.
- Gate 4 as a whole is not complete until Dev C/D/E work lands. DSPy, eval/docs/skills, and full frontend Gate 4 behavior remain owned by their lanes.

## Dev A Gate 4 Lane

Source branch:

```text
codex/dev-a-gate4
```

Added Dev A-owned behavior:

- Expanded `backend/app/clients/bsky.py` for robust public Bluesky URL parsing, DID/handle AT URI construction, and read-only SDK access.
- Normalized target posts, parent context, quote text, external links, image alt text/fullsize/thumb URLs, and unavailable/blocked/deleted warnings.
- Added concise upstream error wrapping so raw provider response bodies do not leak into API details.
- Added a read-only `BlueskyClient.search_posts()` wrapper returning `ContextDocument` objects for retrieval lanes.
- Updated `PostContext.warnings` in domain contracts.
- Added unit/integration coverage for parent, quote, link, image, unavailable, search, and sanitized error behavior.

Important Dev A notes:

- Live unauthenticated `app.bsky.feed.searchPosts` returned `403` in this environment. The wrapper keeps failures typed and sanitized rather than treating unauthenticated live search as final retrieval completion.
- `PostContext.warnings` is normalized by Dev A, but the current Gate 3 adapter does not expose those warnings in public API trace because `backend/app/agent/` is outside Dev A ownership.

## Dev B Gate 4 Lane

Source branch:

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

Important Dev B notes:

- `RagService.retrieve(query, documents) -> Evidence[]` is ready for integration and exposes prompt-injection diagnostics through `last_diagnostics`.
- Optional Qdrant and web extraction paths were verified with extras, not only the base dev environment.
- Dev B's `BlueskySearchProvider` can consume or wrap Dev A's read-only `BlueskyClient.search_posts()` during the integration window.

## Merge Notes

- Dev A and Dev B backend implementation ownership was disjoint: Dev A changed API/Bluesky/schema/test files, while Dev B added retrieval/source-safety modules.
- Merge overlap existed in `docs/current_handoff.md`, `TRANSLATION_LOG.md`, `scripts/verify_lane_isolation.sh`, and `scripts/assert_lane_execution_context.sh`; those files were resolved additively.
- The generic lane verifier keeps strict standalone-clone and shared-worktree checks, and the context guard accepts execution from approved execution roots or subdirectories.
- Preserve Dev A's `BlueskyClient.search_posts()` and `PostContext.warnings` while wiring Dev B retrieval.
- Preserve Dev B's retrieval diagnostics and optional dependency fallback behavior while integrating with Dev C trace/guardrails.

## Verified Commands

Run this before any handoff, commit, or push:

```bash
make deep-review
```

The current passing gate covers linting, typing, backend tests, frontend tests, secret scan, config validation, frontend audit/build, optional backend dependency dry-run, requirement matrix validation, generated artifact cleanup, maintainability review, and user smoke checks.

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

Additional Dev A Gate 4 checks performed before handoff:

```text
bash scripts/verify_lane_isolation.sh assets/dev_A_gate4_WORKSPACE_CONTRACT.json
bash scripts/assert_lane_execution_context.sh assets/dev_A_gate4_WORKSPACE_CONTRACT.json
make deep-review
make check-secrets
git diff --check
live Bluesky fetch_context smoke with https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y
live /api/explain smoke with https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y
live SDK normalization probes for external, image, quote, and record-with-media embeds
```

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

Additional merge checks performed:

```text
git merge --no-ff origin/codex/dev-b-gate4-retrieval-safety
git diff --check
make deep-review
uv run --extra bluesky pytest app/tests/unit/test_fetcher.py app/tests/unit/test_search.py
uv run --extra ai pytest app/tests/unit/test_rag.py::test_qdrant_vector_store_recreate_and_query_when_dependency_available
```

## Important Boundaries

- Do not replace the trace-marked Gate 3 adapter with unmarked fake explanation bullets.
- Do not claim integrated `/api/explain` Search/RAG, DSPy, eval, full guardrails, image understanding, provider comparison, GEPA, or MLflow are complete until their real files, tests, eval artifacts, and matrix rows are updated.
- Real Bluesky post fetch is required for future integration gates.
- Temporary deterministic dev adapters may be used only while real Search/RAG or DSPy modules are incomplete.
- Any dev adapter use must be visible in `trace`.
- Dev adapters cannot satisfy final acceptance or requirement-matrix rows.

## Next Work

Recommended next step: integrate Dev B Search/RAG with Dev A/C service wiring, keep Dev C DSPy/guardrails moving, and keep T1 handoff spine/research deliverables moving through Dev D.

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
