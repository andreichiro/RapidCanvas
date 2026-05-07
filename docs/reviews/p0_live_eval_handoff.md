# P0 Live Eval Handoff

Updated: 2026-05-05
Repository path: `/Users/akatsurada/Documents/RapidCanvas_AI`
Branch: `develop`
Baseline commit before local edits: `404dfdf`
Scope: P0 Live Eval Must Catch Weak Answers

## Objective

Close the live-eval correctness gaps that allowed weak, fallback, or irrelevant
answers to look successful. The work stays inside the eval/report/provider
quality surface and avoids reworking source-quality, retrieval, frontend, or
runtime architecture code that is outside this P0 lane.

## Implementation Summary

- Provider comparison now counts a provider as comparison-complete only when the
  row status is `ran` and the live quality pass criteria succeed.
- Provider comparison now stays `comparison incomplete` when configured providers
  return HTTP 200 but fall back to deterministic/provider-error paths.
- Provider quality scoring now rejects missing execution trace data instead of
  treating absent `adapter_mode` as a clean provider run.
- Provider quality scoring now rejects provider-skip, unknown-provider
  OpenAI fallback, and provider-default warning traces even when
  `adapter_mode=none`.
- Public live quality pass now requires `provider_quality_score >= 1.0`.
- Linked-article expected-point recall now requires a cited `web` or `link`
  source before a linked-article point can count as covered.
- Generic aliases such as `summary` and `summarized` no longer satisfy linked
  article recall by themselves.
- Source relevance scoring now screens catalog, marketplace, trading-card,
  shopping, and SEO-like sources before applying runtime `quality_score`.
- Runtime `quality_score` no longer masks semantic irrelevance. It can only
  fully help when there is meaningful semantic overlap.
- Explicit `citation_eligible: false` citations now fail public live quality,
  source relevance, citation relevance, and live-review failure reporting.
- Risky cited-source runtime metadata, including prompt-injection flags,
  failed fetches, blocked/private/robots-disallowed fetches, and failed HTTP
  statuses, now makes the source eval-ineligible even if upstream source quality
  forgot to set `citation_eligible: false`.
- API eval now separates attempted API rows from true live prediction successes;
  exact-post cache fallback and API-error rows are excluded from `live_case_count`.
- Live quality review rows now include `provider_quality_score`.
- Live quality review rows now include `ineligible_citation_count`.
- Live quality failure reasons now include `provider_quality_failed`.
- Live quality failure reasons now include `ineligible_citation`.
- Provider cost metadata now has a real allow-listed extraction path for usage
  and estimated cost fields, while dropping raw provider payloads.
- Cost metadata strings are redacted before entering quality trace payloads.
- The comprehensive testing strategy now explicitly covers these weak-answer
  probes so future changes do not require line-by-line manual rediscovery.

## Files Changed

- `backend/app/eval/provider_quality.py`
- `backend/app/eval/provider_comparison.py`
- `backend/app/eval/point_recall.py`
- `backend/app/eval/quality_metrics.py`
- `backend/app/eval/quality_policy.py`
- `backend/app/eval/runner.py`
- `backend/app/eval/report.py`
- `backend/app/eval/source_screening.py`
- `backend/app/agent/eval_support.py`
- `scripts/write_live_quality_review.py`
- `backend/app/tests/unit/test_provider_comparison.py`
- `backend/app/tests/unit/test_live_quality_metrics_strategy.py`
- `backend/app/tests/unit/test_live_quality_review.py`
- `backend/app/tests/unit/test_eval_metrics.py`
- `backend/app/tests/unit/test_eval_runner.py`
- `backend/app/tests/unit/test_agent_program.py`
- `backend/app/tests/unit/test_live_quality_metric_edges.py`
- `docs/comprehensive_testing_strategy.md`
- `docs/reviews/staff_line_review_matrix.md`
- `docs/reviews/p0_live_eval_handoff.md`

## Tests Added Or Strengthened

- Provider comparison rejects two provider-fallback HTTP 200 responses.
- Provider comparison rejects two weak live rows from making comparison complete.
- Provider comparison rejects keyword-stuffed catalog sources even when bullet
  text overlaps.
- Provider comparison rejects missing execution trace data as an actual run.
- Linked-article expected-point recall requires cited link or web evidence.
- Public live quality pass rejects deterministic fallback output.
- Public live quality pass rejects missing provider execution trace data.
- Catalog/marketplace sources fail relevance even with inflated runtime quality.
- Marginal-overlap sources cannot be rescued by inflated runtime quality.
- Explicitly ineligible cited sources fail public live quality.
- Prompt-injection source metadata fails public live quality even when the
  top-level source shape otherwise looks usable.
- Failed-fetch source metadata fails public live quality even when the text
  lexically overlaps with the answer.
- Snippet-only sources cannot be the sole public passing support.
- Image-required cases still require cited image evidence.
- Provider fallback/default warning traces fail provider quality and public live
  quality.
- API-mode live counts exclude exact-post cache fallback and API-error rows
  while preserving a separate attempted-row count.
- Live quality report surfaces provider quality and explicit provider-quality
  failure reason.
- Live quality report surfaces ineligible-citation count and explicit failure
  reason.
- Live quality gate blocks any row that is marked meaningful while still
  carrying an ineligible cited source count.
- Provider quality trace includes allow-listed cost metadata when available.
- Provider quality trace drops raw cost payloads and redacts unsafe strings.

## Verification Already Run

Focused P0 regression suite:

```bash
cd backend && uv run pytest \
  app/tests/unit/test_provider_comparison.py \
  app/tests/unit/test_live_quality_review.py \
  app/tests/unit/test_live_quality_metrics_strategy.py \
  app/tests/unit/test_live_quality_metric_edges.py \
  app/tests/unit/test_eval_metrics.py \
  app/tests/unit/test_eval_runner.py \
  app/tests/unit/test_agent_program.py -q
```

Result: `71 passed`.

Full review gate:

```bash
make deep-review
```

Result: passed.

Covered by the full gate:

- Ruff and mypy passed.
- Backend tests passed: `448 passed`.
- Frontend tests passed: `39 passed`.
- Frontend build and audit passed.
- Optional backend dependency dry-run passed.
- Requirements matrix review passed.
- Staff review matrix validation passed.
- Skill validation passed.
- Maintainability review passed.
- API and frontend smoke checks passed.

Cached eval:

```bash
make eval-cached
```

Result: passed.

Important cached summary values:

- `case_count`: `19`
- `api_attempted_case_count`: `0`
- `live_case_count`: `0`
- `public_bluesky_fixture_case_count`: `10`
- `expected_point_recall`: `1.0`
- `final_response_correctness`: `1.0`
- `citation_coverage`: `1.0`
- `unsupported_claim_rate`: `0.0`
- `unsafe_output_rate`: `0.0`
- `off_topic_source_count`: `0.0`
- `ineligible_citation_count`: `0.0`
- `public_live_quality_pass`: `1.0`
- `image_expected_point_recall`: `1.0`
- `latency_p95`: `77.0`

Live eval with transient OpenAI key loaded from ignored local key file:

```bash
OPENAI_API_KEY="$(tr -d '\n' < KEY.TXT)" make eval
OPENAI_API_KEY="$(tr -d '\n' < KEY.TXT)" make live-quality-review
OPENAI_API_KEY="$(tr -d '\n' < KEY.TXT)" make live-quality-smoke
```

Results: passed.

Important live values:

- `make eval`: `expected_point_recall=0.9649122807017543`,
  `final_response_correctness=1.0`, `public_live_quality_pass=0.8`,
  `citation_coverage=1.0`, `unsupported_claim_rate=0.0`,
  `unsafe_output_rate=0.0`, `off_topic_source_count=0.0`,
  `ineligible_citation_count=0.0`, `image_expected_point_recall=0.9824561403508772`,
  `latency_p95=17037.0`, `api_attempted_case_count=19.0`,
  `live_case_count=10.0`, `live_prediction_success_count=10.0`,
  and `exact_post_cache_fallback_count=9.0`.
- `make live-quality-review`: 10 public rows, 8 meaningful passes, 0 failed rows
  without reason, 0 off-topic passing rows, 0 ineligible-citation passing rows,
  0 passing rows with non-live adapter.
- `make live-quality-smoke`: OpenAI ran 2 quality-passing rows; unconfigured
  Anthropic/Gemini/Ollama rows remained skipped with explicit reasons, so
  `comparison_status` stayed `comparison incomplete`.

Provider comparison catalog mode:

```bash
make provider-comparison
```

Result: passed.

Observed summary:

- `mode`: `catalog`
- `ran_provider_count`: `0`
- `comparison_status`: `comparison incomplete`
- Unconfigured providers remain skipped with explicit reasons.

Adjacent acceptance commands:

```bash
make optimize
make mlflow-log
docker compose config
python3 scripts/check_docker_prereqs.py
```

Results:

- `make optimize`: passed.
- `make mlflow-log`: passed and wrote only ignored MLflow artifacts.
- `docker compose config`: passed.
- `python3 scripts/check_docker_prereqs.py`: blocked by local machine state
  (`docker info` timeout and 7.5 GiB free disk, below the 10 GiB threshold).

Gate 7 truth audit:

```bash
make gate7-final-truth-audit
```

Result: failed after its cached eval step passed. The failure reasons were
branch/worktree-truth conditions rather than P0 live-eval metric failures:
unstaged tracked changes are present, the G7-C delta contains out-of-scope paths,
and `origin/codex/g7bc-final-integration` is not at `HEAD`.

Other checks:

```bash
git diff --check
rg "planned-only|unreviewed" docs/reviews/staff_line_review_matrix.md
make check-secrets
```

Results:

- `git diff --check`: passed.
- Staff ledger placeholder search: zero hits.
- `make check-secrets`: passed after live runs; the key was not written to
  tracked files or unignored project files.
- Clean-runtime naming probe still reports production-facing Gate/Dev labels in
  P1 architecture files. That is outside this P0 live-eval patch and remains a
  broader runtime cleanup item.

## Current Review Verdict

For the P0 Live Eval scope, the previously identified gaps are closed at the
code and deterministic-test level:

- Provider fallback responses no longer count as real provider runs.
- Weak provider responses no longer make a provider comparison complete just
  because the model path returned HTTP 200 with `adapter_mode=none`.
- Missing execution trace no longer passes provider quality.
- Provider fallback/default warning traces no longer pass provider quality.
- Linked-article recall no longer passes with thread-only safe-summary text.
- Off-topic catalog sources no longer pass through inflated quality scores.
- Explicitly ineligible citations no longer pass public live quality or aggregate
  live-quality failure checks.
- Risky source metadata now fails public live quality even when upstream
  citation eligibility is absent or inconsistent.
- API eval no longer reports exact-post cache fallback or API-error rows as
  live successes.
- Public live quality pass now encodes provider execution quality.
- Cost metadata is no longer only a placeholder contract when usage data exists.

No new P0 Live Eval code findings remain from the latest review pass.

## Remaining Handoff Notes

- Keep this lane scoped to eval/report/provider-quality behavior.
- Do not broaden into retrieval, UI, finalizer, Qdrant, Bluesky splitting, or
  Docker unless the next task explicitly changes scope.
- Before final commit, inspect `git status --short` and exclude unrelated local
  artifacts.
- If provider-backed live review is run later, the generated report should show
  10 public rows, at least 8 useful passes, explicit reasons for failed rows, no
  off-topic passing rows, and `adapter_mode == none` for passing rows.
- Do not claim a 9.6-10 score from this lane alone. This closes the P0 live eval
  weak-answer gate, not sustained production/live-ops evidence.
