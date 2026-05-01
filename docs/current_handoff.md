# Current Handoff

Updated: 2026-04-30
Repository: `andreichiro/RapidCanvas`
Current baseline: GitHub `main`
Merged Gate 4 lanes: Dev A, Dev B, Dev C, Dev D, and Dev E.

## Current State

- Gate 0 is implemented: scaffold, command surface, secret hygiene, backend health route, React shell, tests, and deep review workflow.
- Gate 1 is implemented: `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement, and `make requirements-review` enforces 45 rows.
- Gate 2 is implemented: FastAPI/domain contracts are frozen in `backend/app/schemas/`, `backend/app/api/routes.py`, and `backend/app/deps.py`.
- Gate 3 is implemented: `/api/explain` performs real Bluesky post/thread fetching and returns a schema-valid cited safe summary.
- Gate 4 Dev A is merged into the baseline: Backend/API/Bluesky normalization covers URL parsing, DID/handle AT URI construction, real thread fetch, parent context, quote text, external links, image alt text/fullsize/thumb URLs, unavailable/blocked warnings, concise upstream error wrapping, and a read-only Bluesky `search_posts()` wrapper returning `ContextDocument` objects.
- Gate 4 Dev B is merged into the baseline: Search/RAG/source-safety modules cover web and Bluesky search adapters, safe linked-page fetching, prompt-injection scanning, sanitization, embeddings, Qdrant/in-memory retrieval, retrieval diagnostics, and reranking.
- Gate 4 Dev E is merged into the baseline: the React frontend is componentized, typed against the API contract, and renders URL/provider input, loading/error states, cited bullets, sources, trust/fallback states, guardrail flags, and a trace panel.
- Gate 4 Dev D is merged into the baseline: eval/docs/skills cover research docs, task packets, local project skills and validators, 18 synthetic cached eval cases, prompt-injection fixtures, deterministic metrics, selectable DSPy/Ragas/composite judges, fake/API eval modes, JSONL/Markdown/confusion/SVG/summary reports, and requirement-matrix coverage.
- Gate 4 Dev C is merged into the baseline:
  - DSPy signature definitions and runner plumbing exist in `backend/app/agent/signatures.py`, `backend/app/agent/runner.py`, `backend/app/agent/dspy_runner.py`, `backend/app/agent/program.py`, `backend/app/agent/loader.py`, and `backend/app/agent/service.py`.
  - Trust scoring, output validation, fallback modes, prompt-injection source labels, and provider-error degradation exist in `backend/app/guardrails/` and `backend/app/agent/`.
  - GEPA dry-run/real compile plumbing exists in `backend/app/eval/optimize.py`, `backend/app/eval/gepa_persistence.py`, and `backend/app/eval/gepa_validation.py`; dry-run saves `backend/app/agent/optimized/program.json`, and real mode saves a loadable compiled DSPy program directory when valid provider credentials produce successful rollouts.
  - MLflow smoke logging and DSPy model packaging exist in `backend/app/ops/mlflow.py`, `backend/app/agent/mlflow_wrapper.py`, and `backend/app/agent/log_mlflow.py`.
- The public `/api/explain` default route now uses the Dev C `AgentExplainerService` and `BlueskyExplainer` program with real Bluesky fetch plus trace-marked thread-context evidence until Gate 5 wires Dev B external Search/RAG retrieval into the route.
- Deterministic Dev C fallback is used when optional DSPy packages, provider credentials, or live provider calls are unavailable; it marks `adapter_mode=deterministic_dev` and emits guardrail/fallback trace fields instead of silently pretending to be a final live model path.
- `R045` remains planned for final real-pipeline enforcement because the current route still uses temporary thread-context evidence rather than full external Search/RAG integration.
- Isolated Lane Protocol is instantiated for Dev C through `assets/dev_C_gate4_WORKSPACE_CONTRACT.json` and wrapper scripts in `scripts/`.

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
- `PostContext.warnings` is normalized by Dev A, but the current route exposes only the warnings emitted by the active service/retriever path.

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
- Similarity, optional HF cross-encoder, and optional DSPy rerankers in `backend/app/ml/rerankers.py`; optional HF setup falls back if model loading fails.
- Unit tests for search, safe fetch, prompt-injection scanning, RAG retrieval, Qdrant optional behavior, and reranker fallback.

Important Dev B notes:

- `RagService.retrieve(query, documents) -> Evidence[]` is ready for integration and exposes prompt-injection diagnostics through `last_diagnostics`.
- Optional Qdrant and web extraction paths were verified with extras, not only the base dev environment.
- Dev B's `BlueskySearchProvider` can consume or wrap Dev A's read-only `BlueskyClient.search_posts()` during the integration window.

## Dev C Gate 4 Lane

Source branch:

```text
codex/dev-c-gate4
```

Added Dev C-owned behavior:

- DSPy signatures for classification, query generation, reranking, explanation, validation, prompt-injection risk, evidence trust, and eval judging.
- Live `DspySignatureRunner` wiring for all defined signatures with deterministic guarded fallback.
- `BlueskyExplainer` orchestration: injection scan, classify, query generation, rerank, trust assessment, explain, validate/revise once, output repair, fallback decision, and schema-valid response construction.
- Source-type-aware `UNTRUSTED_*` labels for post text, thread context, web evidence, and image alt text in both prompt-injection scans and evidence payloads.
- Output guardrails for 3-5 bullets, required citations, unknown citation rejection, forbidden prompt/secret leakage, and fallback-safe cited bullets.
- Trust scoring for low evidence, low source diversity, weak retrieval scores, prompt-injection risk, DSPy trust requests, validation issues, and live provider failures.
- Loader path that configures DSPy from `.env`/settings, exports `OPENAI_API_KEY` before `dspy.configure`, loads optimized DSPy programs when present, and falls back safely when optional live pieces are absent.
- GEPA dry-run and real compile path with reflection LM, train/dev examples, metric feedback, failed-rollout rejection, and compiled-program persistence/loading.
- MLflow run logging and `mlflow.dspy.log_model` packaging inside the active run, using the live DSPy runner path for packaging.
- FastAPI default dependency now routes through Dev C `AgentExplainerService` instead of the old `Gate3Explainer`, while still marking thread-context evidence until Dev B retrieval is connected in Gate 5.

Review follow-ups already fixed:

- Public API bypassed Dev C program.
- GEPA real mode did not optimize, lacked reflection LM, could falsely save auth failures, and did not save/load the compiled DSPy program.
- `make mlflow-log` skipped packaging or packaged the deterministic runner.
- Several DSPy signatures were defined but unused.
- Invalid-shape/unknown-citation outputs could produce fallback text while trace said `fallback_mode=none`.
- DSPy trust fallback flags were ignored by final trust.
- Untrusted labels were generic, inconsistent, or spoofable by raw content.
- `.env` OpenAI keys were not exported before live DSPy calls.
- Live DSPy provider/auth/runtime errors could crash `/api/explain`.
- README status was stale after Dev C Gate 4.

Important Dev C notes:

- Dev C does not claim final Search/RAG route integration; the current route uses trace-marked thread-context evidence until Dev B retrieval is wired into the route in Gate 5.
- Live provider quality depends on optional extras and valid provider credentials.
- The pasted test key was never committed; rotate it before real use because it was shared in plain text.

## Dev E Gate 4 Lane

Source branch:

```text
codex/dev-e-gate4-frontend-ux
```

Added Dev E-owned behavior:

- Componentized React UI for `UrlForm`, `ProviderSelect`, `ResultView`, `CitationChip`, `SourceList`, `TracePanel`, `ErrorBanner`, `TrustBadge`, and `GuardrailFlags`.
- Typed API client in `frontend/src/api/client.ts` with FastAPI detail payload handling and fallback error messages.
- User-facing loading, error, partial-success, abstain, and safe-summary states.
- Cited bullet rendering with citation chips that link to the source list.
- Source list rendering for title, URL, type, and snippet.
- Trace panel toggle for category, queries, warnings, latency, trust score, fallback mode, and guardrail flags.
- Frontend tests for provider selection, successful submit, cited bullets, source cards, trace toggle, partial fallback, abstain fallback, and API errors.
- Browser verification at `http://127.0.0.1:5173/` against the local backend.

Important Dev E notes:

- The final Dev E review fixed the viewport-scaled H1 finding by replacing `clamp(..., 4vw, ...)` with rem-only sizes and discrete media-query steps.
- `scripts/review_quality.py` now fails `make deep-review` if CSS `font-size` uses `clamp()` or viewport units, preventing the heading regression from returning silently.
- Dev E intentionally did not change backend schemas or route contracts; the frontend consumes the existing public API shape and preserves visible adapter/trust/fallback fields.

## Dev D Gate 4 Lane

Source branch:

```text
codex/dev-d-gate4-eval-docs
```

Added Dev D-owned behavior:

- Research docs under `docs/research/` with source links, syntax snippets, selected defaults, rejected alternatives, and implementation consequences.
- `docs/task_packets.md`, `AGENTS.md`, `TRANSLATION_LOG.md`, and requirement-matrix/handoff updates for the five-lane Gate 4 flow.
- Four local project skills under `.codex/skills/`, each with `SKILL.md`, `agents/openai.yaml`, references, and skill-local `quick_validate.py`.
- `scripts/quick_validate.py` plus `make skills-review`, wired into `make deep-review`.
- `eval/posts.yaml` with 18 synthetic cached eval cases and fixtures under `eval/fixtures/`, including prompt-injection, private URL, contradiction, low-evidence, image, link, quote, reply, non-English, and unavailable/deleted scenarios.
- `backend/app/eval/` runner, agents, metrics, judges, report writers, and dataset loaders.
- Eval runner modes for cached fixtures, fake-agent protocol checks, and current FastAPI `/api/explain` API mode.
- Deterministic, DSPy, Ragas, and composite judge backends. DSPy/Ragas use provider-backed judging when `OPENAI_API_KEY` is configured and no-network local review paths otherwise.
- API eval mode records per-case HTTP failures, route/client exceptions, and non-JSON responses as scored `api_eval_error` abstain rows instead of aborting the report.
- Reports include prediction mode, judge backend, cached/live row counts, API/model-call allowance, JSONL rows, Markdown summary, confusion matrix CSV, SVG graph, and summary JSON.
- Numeric judge metrics, including `dspy_judge_*`, are aggregated into `summary.json` and surfaced in Markdown reports; DSPy support/evidence metrics also appear in the SVG graph when present.

Important Dev D notes:

- Default `make eval` remains deterministic/offline and performs no network or model calls.
- These committed synthetic fixture URLs are not counted as the final 10+ real public Bluesky-post eval set. Gate 6 must add or refresh real/fixture-backed public Bluesky post cases before marking that assignment requirement implemented.
- Optional provider-backed judge runs are explicit and generated artifacts remain ignored under `reports/`.
- Provider-backed full cached eval was verified with an ignored local `.env` key before final shipping: 18-case DSPy and Ragas runs completed, with Ragas rows recording `ragas_mode=ragas_llm`.
- Dev D did not claim final runtime Search/RAG/DSPy pipeline completion; the eval harness can score API mode and is ready to score the real pipeline when Gate 5 integration lands.

## Merge Notes

- Dev C was merged on top of GitHub `main`, which already contained Dev A, Dev B, Dev E, and Dev D.
- Conflict resolution was additive: shared docs/logs kept all lane sections, generic lane scripts kept the more capable multi-lane versions from `main`, and Dev C-specific contracts/wrappers were preserved.
- Preserve Dev A's `BlueskyClient.search_posts()` and `PostContext.warnings` while wiring Dev B retrieval.
- Preserve Dev B's retrieval diagnostics and optional dependency fallback behavior while integrating with Dev C trace/guardrails.
- Preserve Dev E's public API client contract and visible adapter/trust/fallback trace fields while the real pipeline replaces temporary evidence sources.
- Preserve Dev D's default offline eval contract while reusing the same runner for explicit API/model-backed integration checks.
- Preserve Dev C's provider-error fallback behavior so bad or missing live model credentials produce schema-valid safe-summary/abstain responses rather than route crashes.

## Verified Commands

Run this before any handoff, commit, or push:

```bash
make deep-review
```

The current passing gate covers linting, typing, backend tests, frontend tests, secret scan, config validation, frontend audit/build, optional backend dependency dry-run, skill validation, requirement matrix validation, generated artifact cleanup, maintainability review, and user smoke checks.

Additional Dev C Gate 4 checks performed before this handoff:

```text
scripts/verify_dev_C_gate4_isolation.sh
scripts/assert_dev_C_gate4_execution_context.sh
cd backend && uv run pytest app/tests/unit/test_agent_program.py app/tests/unit/test_agent_loader_optimize_mlflow.py app/tests/unit/test_gepa_optimize.py app/tests/unit/test_guardrails.py app/tests/unit/test_prompt_injection_labels.py app/tests/unit/test_agent_output_edges.py
cd backend && OPENAI_API_KEY=sk-test-key uv run pytest app/tests/integration/test_api_contracts.py::test_default_explainer_uses_dev_c_agent_program -q
manual `OPENAI_API_KEY=sk-test-key` `/api/explain` reproduction returned HTTP 200, `fallback_mode=safe_summary`, `adapter_mode=deterministic_dev`, and `dspy_provider_error`
make optimize
make mlflow-log
make requirements-review
make check-secrets
make deep-review
```

Additional merged-main checks retained from previous lanes:

```text
Dev A live Bluesky fetch_context and /api/explain smokes with a public bsky.app post.
Dev B optional `--extra bluesky` fetch/search checks and `--extra ai` Qdrant retrieval check.
Dev E browser-use verification at http://127.0.0.1:5173/.
Dev D `make eval`, fake-agent/API eval modes, and optional DSPy/Ragas/composite judge smokes.
```

## Important Boundaries

- Do not replace trace-marked temporary evidence/adapters with unmarked fake explanation bullets.
- Do not claim final integrated `/api/explain` Search/RAG, image understanding, provider comparison, or final no-adapter acceptance until Gate 5+ wires the real pipeline and eval verifies it.
- Real Bluesky post fetch is required and implemented.
- Temporary deterministic fallback is allowed only when live Search/RAG or DSPy provider paths are unavailable or explicitly not yet wired; any such use must be visible in `trace`.
- Dev adapters/fallbacks cannot satisfy final acceptance or `R045`.
- Preserve the no-fake-product-behavior rule: fallback/safe-summary output is allowed only when trace and guardrail fields say so.
- Generated artifacts under `reports/`, `mlruns/`, Qdrant cache, and local secret files must stay ignored.
- Shared repo `/Users/akatsurada/Documents/New project` remains inspection-only for isolated lane work.

## Gate 5 Parallelization Plan

Gate 5 should run on parallel developer branches, then converge through one
serial end-to-end integration review. Gate 6 starts only after Gate 5 lands and
may then be parallelized internally. Gate 7 starts only after Gate 6 lands and
may then be parallelized internally.

The detailed Gate 5 ownership, must-not-edit boundaries, merge order, and final
review criteria live in `docs/gate5_parallelization_plan.md`.

## Gate 6 Parallelization Plan

Gate 6 should run on parallel developer branches only after Gate 5 lands a real
integrated pipeline. Its detailed ownership, must-not-edit boundaries, quality
spine, merge order, and final review criteria live in
`docs/gate6_parallelization_plan.md`.

## Next Work

Recommended next step: start Gate 5 on parallel branches using
`docs/gate5_parallelization_plan.md`. Gate 5 integration should wire Dev B
`RagService` and retrieval diagnostics into Dev C `AgentExplainerService`, carry
Dev A `PostContext.warnings` into trace warnings, keep Dev E's frontend API
contract stable, and run Dev D API/model-backed eval against the integrated
path. Use `docs/gate6_parallelization_plan.md` only after Gate 5 lands.

During the integration window:

- Replace the temporary `ThreadContextEvidenceRetriever` in `backend/app/agent/service.py` or `backend/app/deps.py` with Dev B retrieval while preserving trace visibility.
- Map Dev B `RagService.last_diagnostics` prompt-injection/private-url/source-safety warnings into Dev C trust/trace fields.
- Keep DSPy provider failures guarded with `dspy_provider_error`.
- Run `make deep-review`, `make eval`, `make optimize`, and `make mlflow-log`.

## Gate 5 Dev C C2/C3 Handoff

Dev C's Gate 5 lane exposes the explainer service checkpoint without wiring the
public route. Dev A can instantiate it with:

```python
from app.agent.service import AgentExplainerService, build_agent_explainer_service

service = AgentExplainerService(fetcher=bluesky_client, retriever=dev_b_retriever, settings=settings)
response = service.explain(request)
```

or use `build_agent_explainer_service(...)` for the same C3 service boundary.
With no fixed program supplied, `AgentExplainerService` lazily loads a
provider-aware DSPy program per `ExplainRequest.provider`; missing optional
providers are skipped with trace warnings and the OpenAI/default path remains
the normal configuration. Passing an explicit `program` preserves the current
route-compatible fixed-program behavior.

Dev B-shaped retrieval output is consumed through
`app.agent.evidence_contract.normalize_retrieval_output`. The service accepts
the legacy `(Evidence[], ContextDocument[])` tuple as well as objects or dicts
with `evidence`, `documents` or `context_documents`, `warnings`, `diagnostics`,
`prompt_injection_flags`, `guardrail_flags`, and `source_safety_diagnostics`.
It also accepts JSON-stable document/evidence mappings and Dev B C2
`private_url_blocks`, with the canonical fixture covered by
`backend/app/tests/integration/test_gate5_explainer.py`.
The service now scans visible post/thread/image text for prompt-injection risk
before DSPy query planning. Clean inputs continue through DSPy classification
and query generation; risky inputs use a trusted metadata-only query and record
`query_generation_skipped_prompt_injection_risk`. The service passes queries to
a query-aware retriever when supported and threads retrieval warnings,
source-safety diagnostics, and prompt-injection flags into the final
`ExplainResponse.trace`.

Trace fields emitted by Dev C include category, DSPy-generated queries,
retrieval and provider warnings, trust score, fallback mode, guardrail flags
such as `prompt_injection_risk`, `source_safety_private_url_blocked`,
`unknown_citation`, `uncited_output`, `dspy_provider_error`, and the current
adapter mode/notes. Provider failures still degrade to guarded fallback output
instead of route crashes. Fallback bullets about the visible Bluesky post cite
the stable post source (`S-post`) rather than borrowing a web evidence source.

This satisfies Dev C's C2 and C3 checkpoint responsibility only: the explainer
can consume Dev B-shaped evidence/diagnostics and return a schema-valid
`ExplainResponse` for Dev A to wire. It does not mark final Search/RAG route
wiring, public eval coverage, frontend verification, or C5 end-to-end
acceptance complete.

## Review Records

- `docs/reviews/gate1_final_review.md`
- `docs/reviews/gate2_final_review.md`
- `docs/reviews/gate3_final_review.md`
- Dev C Gate 4 verification is recorded in this handoff and `TRANSLATION_LOG.md`.
