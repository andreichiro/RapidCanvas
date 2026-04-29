# Current Handoff

Updated: 2026-04-29  
Repository: `andreichiro/RapidCanvas`  
Shared baseline branch: `main`
Current isolated Dev A branch: `codex/dev-a-gate4`

## Current State

- Gate 0 is implemented: scaffold, command surface, secret hygiene, backend health route, React shell, tests, and deep review workflow.
- Gate 1 is implemented: `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement, and `make requirements-review` enforces 45 rows.
- Gate 2 is implemented: FastAPI/domain contracts are frozen in `backend/app/schemas/`, `backend/app/api/routes.py`, and `backend/app/deps.py`.
- Gate 3 is implemented: `/api/explain` performs real Bluesky post/thread fetching and returns a schema-valid cited safe summary.
- Search/RAG and DSPy are still deterministic dev adapters and every Gate 3 response marks this in `trace`.
- `R045` is partially exercised by Gate 3 adapter tracing but remains planned for final real-pipeline enforcement.
- Post-review Gate 3 matrix fix is applied: `R008` now points to actual smoke/browser verification files and commands.
- Gate 4 Dev A lane is implemented on `codex/dev-a-gate4`: Backend/API/Bluesky normalization now covers URL parsing, DID/handle AT URI construction, real thread fetch, parent context, quote text, external links, image alt text/fullsize/thumb URLs, unavailable/blocked warnings, concise upstream error wrapping, and a read-only Bluesky `search_posts()` wrapper returning `ContextDocument` objects.
- Gate 4 as a whole is not complete until Dev B/C/D/E work lands. Search/RAG, DSPy, eval/docs/skills, and full frontend Gate 4 behavior remain owned by their lanes.

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

The live `/api/explain` smoke returned `200`, 3 bullets, `fallback_mode=safe_summary`, and `adapter_mode=deterministic_dev`, preserving the explicit non-final adapter boundary.

Live unauthenticated `app.bsky.feed.searchPosts` returned `403` in this environment. The wrapper now sanitizes upstream errors to concise messages such as `Unable to search Bluesky posts: UnauthorizedError status=403`; Dev B should treat live Bluesky search auth/fallback behavior as part of the retrieval/search lane.

## Important Boundaries

- Do not replace the trace-marked Gate 3 adapter with unmarked fake explanation bullets.
- Do not claim Search/RAG, DSPy, eval, guardrails, image understanding, provider comparison, GEPA, or MLflow are complete until their real files, tests, eval artifacts, and matrix rows are updated.
- Real Bluesky post fetch is required for future integration gates.
- Temporary deterministic dev adapters may be used only while real Search/RAG or DSPy modules are incomplete.
- Any dev adapter use must be visible in `trace`.
- Dev adapters cannot satisfy final acceptance or requirement-matrix rows.
- `PostContext.warnings` is normalized by Dev A, but the current Gate 3 adapter does not expose those warnings in public API trace because `backend/app/agent/` is outside Dev A ownership.
- Dev A added `assets/dev_A_gate4_WORKSPACE_CONTRACT.json`, `scripts/verify_lane_isolation.sh`, and `scripts/assert_lane_execution_context.sh` in the isolated clone so future Dev A work can verify that implementation commands are not run from the shared checkout.

## Next Work

Recommended next step: merge Dev A through normal review, then continue T1 handoff spine/research deliverables and the remaining Gate 4 lanes. Dev B can consume `BlueskyClient.search_posts()` or wrap it behind the search provider protocol; Dev C can consume normalized `PostContext.warnings` when guardrail trace integration lands.

Expected additions:

- `docs/research/*.md`
- `.codex/skills/*`
- `docs/task_packets.md`
- updated `AGENTS.md`, `README.md`, `TRANSLATION_LOG.md`, and `docs/requirements_matrix.md`

After T1, replace deterministic adapters with real Search/RAG and DSPy modules while preserving the no-fake-product-behavior rule.

## Review Records

- `docs/reviews/gate1_final_review.md`
- `docs/reviews/gate2_final_review.md`
- `docs/reviews/gate3_final_review.md`
