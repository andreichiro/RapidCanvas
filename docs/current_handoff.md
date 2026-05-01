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
- Similarity, optional HF cross-encoder, and optional DSPy rerankers in `backend/app/ml/rerankers.py`; optional HF setup falls back if model loading or prediction fails.
- Unit tests for search, safe fetch, prompt-injection scanning, RAG retrieval, Qdrant optional behavior, and reranker fallback.

Important Dev B notes:

- `RagService.retrieve(query, documents) -> Evidence[]` is ready for integration and exposes prompt-injection diagnostics through `last_diagnostics`.
- Optional Qdrant and web extraction paths were verified with extras, not only the base dev environment.
- Dev B's `BlueskySearchProvider` can consume or wrap Dev A's read-only `BlueskyClient.search_posts()` during the integration window.

## Dev B Gate 5 Lane
Source branch: `codex/dev-b-gate5-retrieval-safety`
Gate 5 Dev B checkpoint C2 is implemented in the isolated lane clone at `/Users/akatsurada/Documents/rapidcanvas_dev_b_gate5`:

- `retrieval_service.py`, `retrieval_adapter.py`, and `retrieval_payload.py` expose the C2 service, sync Dev C adapter, and canonical JSON payload helpers.
- The service accepts Dev A `PostContext` plus supplied/generated queries and returns `RetrievalResult` with sanitized documents, ranked evidence, diagnostics, warnings, guardrail flags, source ids, scores, queries, and private/local URL block evidence.
- Dev C can call `await build_retrieval_service().retrieve(...)` or use `RetrievalEvidenceRetriever` for the current sync evidence protocol with invocation-scoped diagnostics.
- Stable fields are `documents`, `evidence`, `warnings`, `guardrail_flags`, `source_ids`, `scores`, `queries`, `private_url_blocks`, and `diagnostics`.
- Diagnostics map to trace warnings, `prompt_injection_risk`, retrieval/eval source-score metadata, and private URL block evidence.
- Evidence ordering preserves raw reranker order; public scores are finite 0..1 values.
- C2 fixture artifacts use the canonical retrieval payload shape under `backend/app/tests/fixtures/gate5_retrieval/`, with integration coverage in `backend/app/tests/integration/test_gate5_retrieval.py`.

Important Dev B Gate 5 notes:
- Production builder uses `OpenAIEmbeddingProvider` by default; deterministic embeddings are injected only in tests.
- Qdrant local mode is preferred by the builder. If Qdrant cannot be created, the service
  falls back to the in-memory vector store with an explicit `qdrant_unavailable_using_in_memory_vector_store:*` warning.
- Bluesky search is read-only through Dev A `BlueskyClient.search_posts()` when
  the default builder is used; builder/per-call settings can disable Bluesky or
  web search, and live provider failures are surfaced as warnings.
- Search providers return per-call warnings, cap output, avoid concurrent warning leaks, degrade provider failures/invalid bundles safely, bound DDGS iteration, skip zero-limit live searches, and use the same resolver-aware source URL policy in direct Bluesky and final retrieval paths.
- Built-in provider `last_warnings`, direct `RagService.last_diagnostics`, and the Dev C retrieval adapter keep diagnostics scoped to the current invocation across async tasks and threaded callers while preserving direct-component accessor shapes.
- Retrieval/evidence/query/reranker limits clamp to non-negative values; zero
  retrieval/evidence limits and malformed embedding/vector runtime output skip model work safely.
- For deterministic/offline C2 or controlled Dev C handoff runs, call
  `build_retrieval_service(..., search_providers=[])`; that explicit empty list
  is preserved and does not install default live search providers.
- DDGS web search and linked-page fetch are read-only. The fetcher blocks
  malformed, credential-bearing, private, localhost, link-local, non-global IP,
  and unsupported-scheme URLs before fetch and before redirects; it also validates
  the connected peer address before accepting response bytes. URL diagnostics
  redact userinfo, query strings, and fragments.
- Linked-page fetches are capped by `RetrievalSettings.linked_page_limit` so
  untrusted post context cannot drive unbounded outbound GET attempts; overflow
  is surfaced as `linked_page_limit_exceeded:*`.
- Returned documents are sanitized and prompt-injection scanned across titles,
  body text, bounded string metadata, and decoded bytes metadata. Retrieval
  filters unsafe source URLs, including normalized provider pass-through docs,
  into private/local block evidence; parser failures return
  `extraction_failed:<ExceptionType>`.
- Normalized Bluesky source metadata may preserve `at://...` AT URIs for
  Bluesky/thread documents; those identifiers are never fetch targets.
- C2 invariant coverage verifies sanitized docs, resolver-safe HTTP source URLs, promoted private/local blocks, valid evidence IDs/source links, finite scores, JSON-stable metadata, malformed handoff/provider/diagnostic shapes, safe text coercion, RAG diagnostics, vector payloads, direct accessor compatibility, adapter/provider/RAG state isolation, and embedding/vector/reranker runtime failures.
- This lane does not wire retrieval into `/api/explain`, does not implement DSPy
  explanations, and does not close final Search/RAG requirement rows. C5 owns
  final end-to-end acceptance.
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

## Dev A Gate 5 Lane - C0/C1 API And Bluesky Handoff
Standalone execution root: `/Users/akatsurada/Documents/rapidcanvas_dev_a_gate5_isolated`
Source branch: `codex/dev-a-gate5-api-bluesky`

Dev A Gate 5 changes are intentionally limited to C0/C1:

- Public routes remain stable: `GET /api/health`, `GET /api/providers`, and
  `POST /api/explain` keep the existing shape.
- `PostContext` remains backward-compatible and now includes target `metadata`,
  structured `parent_posts`, `quoted_posts`, `external_links`, image
  `thumb_url`/`fullsize_url`, legacy text/link lists, `at_uri`, author,
  creation time, and warning strings.
- Bluesky normalization stays inside Dev A-owned
  `backend/app/clients/bsky.py` while preserving real public-read URL parsing,
  handle/DID resolution, thread fetch, parent, quote, link, image, and
  unavailable/blocked warning handling.
- `backend/app/deps.py` wraps current retrievers for request-local warnings and
  lazily composes Dev C `build_agent_explainer_service` with Dev B
  `build_retrieval_service` when both PRs are present on the final C5 branch.
- The C1 handoff fixture lives in
  `backend/app/tests/integration/test_gate5_real_pipeline.py` as
  `build_gate5_c1_post_context_fixture()`. Dev B can consume the returned
  `PostContext` directly for retrieval tests without schema adapters.

Live Bluesky limitations:

- The cached C1 fixture performs no network calls. Live public post/thread fetch
  still depends on Bluesky AppView availability and public visibility of the
  target, parent, and quoted posts.
- Target post unavailability remains a typed sanitized `BlueskyClientError`.
  Parent/quote unavailable or blocked records are non-fatal warnings on
  `PostContext.warnings` and now surface through API trace when the current
  dependency builder is used.

Remaining Gate 5 work:

- Dev B PR #3 and Dev C PR #4 still need to be combined for C5; final
  `/api/explain` becomes real only when both builders are present together.
- Dev A's route layer only wires API/dependency composition and discovers their
  stable builders lazily once present; it does not reimplement retrieval, DSPy,
  trust scoring, fallback policy, output validation, eval, or UI rendering.
- Dev E should receive this handoff to confirm whether the stable public API
  response/trace requires UI changes; Dev D should receive it for final Gate 5
  review artifacts, requirement-matrix closure, docs, and eval bookkeeping.

Dev A Gate 5 verification before handoff includes lane guards, focused
API/Bluesky lint/type/tests, and the required `make setup`, `make lint`,
`make test`, `make requirements-review`, `make check-secrets`, and
`make deep-review` gates.

Review follow-ups fixed: warning propagation now uses request-local context
state; helper/runtime test files were removed; and nested quoted-post timestamps
and CIDs are preserved inside explicit Dev A owned paths.

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

- Replace `ThreadContextEvidenceRetriever` in `backend/app/agent/service.py` or `backend/app/deps.py` with `RetrievalEvidenceRetriever` while preserving trace visibility.
- Map Dev B `RagService.last_diagnostics` prompt-injection/private-url/source-safety warnings into Dev C trust/trace fields.
- Keep DSPy provider failures guarded with `dspy_provider_error`.
- Run `make deep-review`, `make eval`, `make optimize`, and `make mlflow-log`.

## Review Records

- `docs/reviews/gate1_final_review.md`
- `docs/reviews/gate2_final_review.md`
- `docs/reviews/gate3_final_review.md`
- Dev C Gate 4 verification is recorded in this handoff and `TRANSLATION_LOG.md`.
