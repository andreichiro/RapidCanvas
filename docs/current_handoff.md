# Current Handoff

Updated: 2026-05-06
Repository: `andreichiro/RapidCanvas`
Current baseline: Gate 7 final A/B/C integration branch
`codex/g7bc-final-integration` from `origin/main` Gate 6 integration commit
`4728cc3`.
Active lane owner: Dev G7-C final truth/docs/submission consuming G7-A/G7-B evidence.
GitHub file-list labels were refreshed with the final beyond-scope note commit.

## Gate 7 Final Truth Snapshot

- P0 source quality and citation eligibility are now implemented as a
  deterministic runtime policy: search/fetch metadata is normalized, sources get
  quality scores/reasons/eligibility/roles, RAG combines vector, reranker,
  quality, and channel-prior scores, public citations exclude ineligible sources
  and snippet-only evidence unless secondary, and trust scoring downgrades weak,
  off-topic, ineligible, single-source, or snippet-only support.
- P0 claim support, citations, and explanation usefulness are now implemented:
  factual bullets are checked against cited source text for material terms,
  dates, named entities, and causal/definition/announcement markers; revisions
  and final repair re-run the same support map; unsafe echoes use the explicit
  `unsafe_echo` label; DSPy validation labels are normalized to the explicit
  support contract; snippet-only document metadata is mapped to public citation
  source IDs; live metrics score cited sources for relevance/off-topic checks;
  and source-backed partial fallbacks can pass usefulness without letting normal
  abstentions pass.
- Latest transient-key proof for this P0: `make eval-cached` passed with
  `public_live_quality_pass=1.0`, `OPENAI_API_KEY=... make eval` passed with 10
  true live successes plus 9 exact-post cache fallbacks and
  `public_live_quality_pass=0.8`, `OPENAI_API_KEY=... make live-quality-review`
  passed with 9/10 useful rows and zero off-topic/ineligible/non-live-adapter
  passing rows, and `OPENAI_API_KEY=... make live-quality-smoke` passed with
  OpenAI configured and other providers explicitly skipped.
- Gate 6 is landed and reproducible in the Gate 7 integration clone: `make setup`,
  `make eval-cached`, `make requirements-review`, `make check-secrets`, and
  `make deep-review` all passed.
- `make gate7-final-truth-audit` now checks the final truth table, real GEPA
  metadata, compiled artifact presence, partial/reserved wording, eval counts,
  allowed Gate 7 integration file scope, and generated-artifact hygiene.
- Default `make eval` is now the first-class live API quality path and requires
  `OPENAI_API_KEY`. It uses bounded retrieval limits, parallel case execution,
  and exact-post cache fallback only when the cached prediction URL matches the
  eval case URL. `make eval-cached` remains the fixture-backed offline audit
  path with 19 cached cases, 10 fixture-backed public Bluesky URLs, and 9 marked
  synthetic attack/edge fixtures. Expected key points remain the curated truth
  layer.
- Runtime Search/RAG is a real one-shot integrated route when modules and
  providers are available. `ThreadContextFallbackRetriever` remains only an
  explicit fallback/injected path. Capped adaptive retrieval is enabled with max
  one extra safe query, pre-retrieval prompt-injection skip, and trace warnings.
- P1 clean runtime architecture is now enforced in production code:
  dependency wiring uses `_build_runtime_explainer()` and
  `_runtime_retrieval_settings()`, fallback trace output uses
  `thread_context_fallback_guardrails_active`, public adapter mode is
  `deterministic_fallback` (rendered as deterministic fallback), and
  `scripts/review_quality.py` fails on old production-facing Gate/Dev labels.
- P1 finalization is decoupled from `BlueskyExplainer` internals:
  `FinalizationContext` now lives at the finalization boundary, the finalizer
  accepts a typed `finalization_context()` protocol instead of `Any`, and tests
  prove a context-only object can finalize a response without private program
  fields.
- P1 Qdrant concurrency and retrieval scalability are now implemented:
  vector-store calls use `ensure_collection()`, namespace-scoped `upsert()` and
  `query()`, and `clear_namespace()` instead of shared collection recreation;
  Qdrant collection names are model/dimension scoped; request namespaces include
  a stable post/query fingerprint plus a per-request suffix; in-memory fallback
  is namespace-isolated; linked-page fetch and search collection run with bounded
  concurrency, deterministic ordering, and partial-result timeout warnings.
  Acceptance tests now scan production vector code for shared collection
  deletion/recreation regressions and assert namespace lifecycle signatures.
- P1 safe fetch, robots, and search stability are now implemented:
  linked-page fetches validate public HTTP(S) targets, userinfo, DNS, redirects,
  peer addresses, content types, extraction, and robots.txt before accepting
  page evidence. Robots checks use a small-timeout cached policy: explicit
  disallow prevents page fetch, transient robots failures degrade to warnings,
  and web search may keep only a snippet-only low-confidence fallback that is
  marked `robots_disallowed` and rejected for citation eligibility.
- The frontend now requires a masked OpenAI API-key field, and the default
  backend route requires either that transient `api_key` or local
  `OPENAI_API_KEY` before it runs embeddings/model-backed explanations. The
  field is not stored in the repo or browser local storage.
- User-facing bullets are now explicitly generated/validated in English. The
  deterministic fallback no longer echoes non-English visible post text; it
  emits an English fallback instead when the post language is non-English.
- Bluesky video embeds are supported as a degraded path: the post still flows
  through text/thread/link/image retrieval, while trace/UI warnings mark
  `video_embed_unparsed` so the app does not pretend to parse video frames.
- Local startup now has one-command paths: `make run` starts the Docker Compose
  stack for UI, API, Qdrant, and MLflow; `make dev` starts or reuses fixed-port
  source dev servers in one terminal. The frontend also falls back from `/api`
  to `http://127.0.0.1:8000` to avoid generic local `Failed to fetch` errors
  when the backend is reachable.
- Ops hardening is implemented for the local review path: `make docker-up` runs
  `scripts/check_docker_prereqs.py`, Docker Compose gates services with
  healthchecks, FastAPI attaches sanitized `X-Request-ID` request context/logs,
  and rate limiting trusts `X-Forwarded-For` only from configured proxy hosts.
  CI now runs `make eval-cached` after `make deep-review`; live quality has a
  separate manual workflow that requires the repository `OPENAI_API_KEY` secret
  and uploads ignored report artifacts.
- GEPA in this integration branch is real compiled metadata at
  `backend/app/agent/optimized/program.json` with a saved DSPy program under
  `backend/app/agent/optimized/program_compiled/`. The examples come from
  finalized cached Gate 6 eval fixtures.
- Image support is default-enabled runtime vision evidence for image posts when
  a request key or local `OPENAI_API_KEY` is available, with capped/sanitized
  untrusted alt-text fallback when vision is unavailable. Image trace rows now
  carry `vision_model`, `vision_used`, `alt_text_used`, `image_evidence_role`,
  `image_index`, `vision_warning`, and `prompt_injection_flags`; no-alt/no-vision
  images degrade to a non-citable diagnostic source rather than disappearing.
  Cached eval reports `image_expected_point_recall=1.0` and
  `image_evidence_used=1.0`. G7-C ran a live helper smoke: one upstream image URL
  failed to download, and a second public image succeeded in 3.3s. This is not a
  full browser/UI visual QA pass.
- Provider comparison now has a generated report path through
  `make provider-comparison` plus a configured-provider live smoke command
  through `make live-quality-smoke`; selecting Anthropic with only the OpenAI
  request key was smoke-tested and fell back to OpenAI with trace warnings. no
  live Anthropic/Gemini/Ollama benchmark ran.
- Docker Compose build and startup were verified locally: backend health, frontend, Qdrant, and MLflow all responded. Test volumes were removed afterward.
- MLflow local file-backed logging was verified with `make mlflow-log`; generated
  `backend/mlruns/` and report manifests remain ignored.
- Ragas/DSPy judge provider-backed runs were not launched by G7-C. Default eval
  stays deterministic/no-network; Gate 6 records explicit optional offline judge
  smokes.
- G7-C API-mode smoke over all 10 fixture-backed public Bluesky URLs first hit
  the live route without a provider key and returned safe cited abstentions.
  Final closure then added the transient request-key path and verified two
  public Bluesky URLs with provider-backed routing: both returned 200,
  `adapter_mode=none`, web/thread sources, and 3-4 cited bullets.
- A final reported-post smoke for
  `https://bsky.app/profile/fonsiloaizap.bsky.social/post/3mkqt5qidf22l`
  returned 200 in 47.43s with `adapter_mode=none`, `fallback_mode=partial`,
  4 English cited bullets, thread/web sources, and a `video_embed_unparsed`
  warning.
- The OpenAI key pasted in chat was used only as transient request input for
  that live route smoke. It was not written to tracked files or docs. Rotate it
  before real use because it appeared in chat.
- Final review: `docs/reviews/gate7_final_review.md`.
- Final branch/push status: branch `codex/g7bc-final-integration` contains the
  G7-C docs branch, G7-B commit `3a79056`, and G7-A commit `fc4dff4`. The Gate 7
  audit checks that the tracked tree is clean and `origin/codex/g7bc-final-integration`
  matches local `HEAD`.

## Current State

- Gate 0 is implemented: scaffold, command surface, secret hygiene, backend health route, React shell, tests, and deep review workflow.
- Gate 1 is implemented: `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement, and `make requirements-review` enforces 45 rows.
- Gate 2 is implemented: FastAPI/domain contracts are frozen in `backend/app/schemas/`, `backend/app/api/routes.py`, and `backend/app/deps.py`.
- Gate 3 is implemented: `/api/explain` performs real Bluesky post/thread fetching and returns a schema-valid cited safe summary.
- Gate 4 Dev A is merged into the baseline: Backend/API/Bluesky normalization covers URL parsing, DID/handle AT URI construction, real thread fetch, parent context, quote text, external links, image alt text/fullsize/thumb URLs, unavailable/blocked warnings, concise upstream error wrapping, and a read-only Bluesky `search_posts()` wrapper returning `ContextDocument` objects.
- P1 Bluesky client split is implemented: `backend/app/clients/bsky.py` is a thin read-only ATProto wrapper, while `bsky_url.py`, `bsky_embeds.py`, and `bsky_normalize.py` own URL/AT URI helpers, embed extraction, thread normalization, deterministic timestamp fallback, and visible malformed/missing timestamp warnings.
- Gate 4 Dev B is merged into the baseline: Search/RAG/source-safety modules cover web and Bluesky search adapters, safe linked-page fetching, prompt-injection scanning, sanitization, embeddings, Qdrant/in-memory retrieval, retrieval diagnostics, and reranking.
- Gate 4 Dev E is merged into the baseline: the React frontend is componentized, typed against the API contract, and renders URL/provider input, a masked required OpenAI API-key field, loading/error states, cited bullets, sources, trust/fallback states, guardrail flags, and a trace panel.
- Gate 4 Dev D is merged into the baseline: eval/docs/skills cover research docs, task packets, local project skills and validators, 18 synthetic cached eval cases, prompt-injection fixtures, deterministic metrics, selectable DSPy/Ragas/composite judges, fake/API eval modes, JSONL/Markdown/confusion/SVG/summary reports, and requirement-matrix coverage.
- Gate 4 Dev C is merged into the baseline:
  - DSPy signature definitions and runner plumbing exist in `backend/app/agent/signatures.py`, `backend/app/agent/runner.py`, `backend/app/agent/dspy_runner.py`, `backend/app/agent/program.py`, `backend/app/agent/loader.py`, and `backend/app/agent/service.py`.
  - Trust scoring, output validation, fallback modes, prompt-injection source labels, and provider-error degradation exist in `backend/app/guardrails/` and `backend/app/agent/`.
  - GEPA dry-run/real compile plumbing exists in `backend/app/eval/optimize.py`, `backend/app/eval/gepa_persistence.py`, and `backend/app/eval/gepa_validation.py`; dry-run saves `backend/app/agent/optimized/program.json`, and real mode saves a loadable compiled DSPy program directory when valid provider credentials produce successful rollouts.
  - MLflow smoke logging and DSPy model packaging exist in `backend/app/ops/mlflow.py`, `backend/app/agent/mlflow_wrapper.py`, and `backend/app/agent/log_mlflow.py`.
- Gate 5 C5 integration branch `codex/gate5-c5-integration` now wires the public route through real Bluesky fetch, Dev B `RetrievalEvidenceRetriever`, and Dev C provider-aware `AgentExplainerService`; missing live dependencies or credentials degrade with trace-visible diagnostics.
- Dev E PR #7 is merged into C5 and verifies real-response rendering, citation/source navigation, trust/fallback badges, guardrail flags, and trace diagnostics in the frontend.
- `R045` is closed for C5 runtime enforcement only when the real pipeline modules are present and any fallback/dev adapter use is trace-marked; real public eval rows remain Gate 6 work.
- Gate 6 Dev A API smoke stability is the lane baseline at `57aefac`.
  It proves the public schema is unchanged, `/api/explain` still builds the
  Gate 5 service path, trace fields are present, source IDs validate, invalid
  URLs are clean, and errors are sanitized.
- Gate 6 Dev D rapid quality layer is implemented in this branch:
  `make eval-cached` now runs 19 cached cases, including 10 fixture-backed public
  Bluesky URLs verified on 2026-05-01 and 9 clearly marked synthetic attack or
  edge fixtures.
- Gate 6 readiness automation now checks case mix, public/synthetic provenance,
  fixture API shape, citation references, and report-summary honesty fields.
- The Gate 6 default report writes JSONL, Markdown, summary JSON, confusion
  matrix CSV, and SVG graph artifacts under ignored `reports/eval/`.
- `make eval-cached` remains deterministic/offline. It records explicit skip
  reasons for Ragas, DSPy judge, and MLflow. Explicit offline DSPy, Ragas, and
  MLflow runs were also verified after `make setup`.
- Isolated Lane Protocol is instantiated for Dev D through `assets/dev_D_gate6_WORKSPACE_CONTRACT.json` and wrapper scripts in `scripts/`.
- Gate 6 integration branch `gate6/integration` was created in standalone clone
  `/Users/akatsurada/Documents/rapidcanvas_gate6_integration_isolated` from Dev A `57aefac`; Dev D then merged Dev D, Dev B, Dev C, and Dev E lanes.
- Integrated lane heads: Dev A `57aefac`, Dev D `d7d0da6`, Dev B `f3e1d2c`,
  Dev C `0664d07`, and Dev E `a969a59`. No available Gate 6 lane was skipped.
- Merge result: all branches merged cleanly, no broad conflicts, no generated artifacts/secrets/Qdrant/MLflow/live outputs tracked, and generated `reports/eval/` remains ignored.

## Historical Lane Summary

Detailed Gate 4-6 lane history is preserved in `TRANSLATION_LOG.md`,
`docs/reviews/gate5_final_review.md`, and
`docs/reviews/gate6_final_review.md`. The current implementation contains:

- Dev A: Bluesky URL parsing, read-only post/thread fetch, search wrapper,
  parent/quote/link/image normalization, and sanitized API errors.
- Dev B: safe web/Bluesky search, linked-page fetch, prompt-injection scanning,
  embeddings, Qdrant/in-memory retrieval, reranking, retrieval diagnostics, and
  the `RetrievalEvidenceRetriever` route adapter.
- Dev C: DSPy signatures/program, provider-aware loading, trust/output
  guardrails, source labels, GEPA dry-run/real-mode plumbing, and MLflow
  local logging/package helpers.
- Dev D: research docs, task packets, local skills, cached eval fixtures,
  metrics, reports, optional judge paths, and requirement-matrix reviews.
- Dev E: React UI for URL/provider input, cited bullets, sources,
  trust/fallback states, guardrail flags, trace diagnostics, and frontend tests.

## Merge Notes

- Dev C was merged on top of GitHub `main`, which already contained Dev A, Dev B, Dev E, and Dev D.
- Conflict resolution was additive: shared docs/logs kept all lane sections, generic lane scripts kept the more capable multi-lane versions from `main`, and Dev C-specific contracts/wrappers were preserved.
- Preserve Dev A's `BlueskyClient.search_posts()` and `PostContext.warnings` while wiring Dev B retrieval.
- Preserve Dev B's retrieval diagnostics and optional dependency fallback behavior while integrating with Dev C trace/guardrails.
- Preserve Dev E's public API client contract and visible adapter/trust/fallback trace fields while the real pipeline replaces temporary evidence sources.
- Preserve Dev D's offline `make eval-cached` contract while making `make eval`
  the live API quality path with exact-post cache fallback.
- Preserve Dev C's provider-error fallback behavior so bad live model
  credentials produce schema-valid safe-summary/abstain responses rather than
  route crashes. Missing credentials on the default public route should fail
  fast with `missing_openai_api_key` instead of pretending embeddings ran.

## Verified Commands

Run this before any handoff, commit, or push:

```bash
make deep-review
```

The current passing gate covers linting, typing, backend tests, frontend tests, secret scan, config validation, frontend audit/build, optional backend dependency dry-run, skill validation, requirement matrix validation, generated artifact cleanup, maintainability review, and user smoke checks.
The full live/cached/user-flow review strategy is recorded in
`docs/comprehensive_testing_strategy.md`.

Gate 6 integration checks performed in the standalone integration clone:

```text
Dev A baseline check: cd backend && uv run pytest app/tests/integration/test_api_contracts.py app/tests/integration/test_gate6_api_eval_smoke.py -q
Dev D smoke after merge: make gate6-shipping-audit
Dev B smoke after merge: cd backend && uv run pytest app/tests/integration/test_gate6_retrieval_metrics.py app/tests/unit/test_rag.py app/tests/unit/test_prompt_injection.py -q
Dev C smoke after merge: cd backend && uv run pytest app/tests/unit/test_agent_quality_support.py app/tests/unit/test_gate6_dev_c_quality_contract_review.py app/tests/unit/test_mlflow.py app/tests/integration/test_gate6_agent_quality_hooks.py app/tests/unit/test_guardrails.py -q
Dev E smoke after merge: npm --prefix frontend test -- src/test/gate6-quality-contract.test.ts src/test/gate6-quality-response.test.tsx
```

Additional merged-main checks retained from previous lanes:

```text
Dev A live Bluesky fetch_context and /api/explain smokes with a public bsky.app post.
Dev B optional `--extra bluesky` fetch/search checks and `--extra ai` Qdrant retrieval check.
Prior Dev E browser-use verification at http://127.0.0.1:5173/; G7-C did not
  run a fresh browser-use pass.
Dev D `make eval-cached`, fake-agent/API eval modes, and optional DSPy/Ragas/composite judge smokes.
Gate 7 closure transient-key route smoke: two public Bluesky URLs returned 200,
`adapter_mode=none`, web/thread sources, and 3-4 cited bullets; no generated
live report was tracked.
Final Gate 7 local smoke: `make dev` reached healthy API/UI/proxied providers,
NYTimes public post returned a normal 3-bullet cited answer in 28.62s, Anthropic
selection fell back to OpenAI with provider warnings in 30.22s, and live vision
helper passed on a public image in 3.3s.
```

## Important Boundaries

- Do not replace trace-marked temporary evidence/adapters with unmarked fake explanation bullets.
- Do not claim a broad live vision benchmark, a full browser/UI vision pass, or
  a live multi-provider benchmark. Gate 6 public eval is fixture-backed and
  cached, not a live refetch benchmark.
- Real Bluesky post fetch is required and implemented.
- The C5 route attempts the integrated real Search/RAG plus DSPy path by default; fallback/dev adapter use is acceptable only when `trace` marks the retrieval/provider downgrade.
- `R045` is satisfied by C5/G7 enforcement artifacts, not by no-key fallback
  output. The default UI/API path now requires a key before embeddings/model
  calls; no-key abstain output remains only historical limitation evidence.
- Gate 6 public eval coverage is fixture-backed through `make eval-cached`. It
  closes the 10+ public Bluesky eval-case requirement without pretending that
  synthetic `example.com` URLs are public posts.
- Live provider-backed quality is partially smoke-tested for wiring on two
  public posts. Broader API-mode benchmarking now belongs to default
  `OPENAI_API_KEY=... make eval`.
- Preserve the no-fake-product-behavior rule: fallback/safe-summary output is allowed only when trace and guardrail fields say so.
- Generated artifacts under `reports/`, `mlruns/`, Qdrant cache, and local secret files must stay ignored.
- Shared repo `/Users/akatsurada/Documents/New project` remains inspection-only for isolated lane work.

## Gate 6 Dev D Rapid Handoff

The standalone lane clone and branch are
`/Users/akatsurada/Documents/rapidcanvas_dev_d_gate6_isolated` and
`codex/dev-d-gate6-eval-reports`; isolation passed before implementation.
The concise Gate 6 evidence package lives in
`docs/reviews/gate6_final_review.md` and `docs/gate6_eval_methodology.md`.
Default `make eval-cached` writes ignored artifacts under `reports/eval/` and reports
19 cached rows: 10 fixture-backed public Bluesky URLs and 9 synthetic attack or
edge fixtures. The summary exposes `public_bluesky_fixture_case_count` and
`ragas_metric_source`; DSPy judge, Ragas, and MLflow were also run explicitly.
Raw attack payloads are inventoried in `eval/fixtures/prompt_injection/manifest.json`
and enforced by the Gate 6 readiness test.
Cached eval remains offline and reports those optional paths separately. Gate 7
closure added the required transient key path and verified two provider-backed
public route smokes; default `make eval` now uses the same live route with an
exact-post cache fallback policy.

## Review Records

- `docs/reviews/gate1_final_review.md`
- `docs/reviews/gate2_final_review.md`
- `docs/reviews/gate3_final_review.md`
- `docs/reviews/gate5_final_review.md`
- `docs/reviews/gate6_final_review.md`
- Dev C Gate 4 verification is recorded in this handoff and `TRANSLATION_LOG.md`.
