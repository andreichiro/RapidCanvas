# Comprehensive Testing Strategy

This strategy defines how RapidCanvas proves the Bluesky explainer works as an
application, not only as isolated modules. It complements `make deep-review` and
the final truth audit by separating live quality checks from deterministic
reproducibility checks.

## Critical Path

Run these before shipping any code that can affect the user flow:

```bash
make deep-review
OPENAI_API_KEY=... make eval
make eval-cached
make gate7-final-truth-audit
make check-secrets
```

- `make deep-review` covers linting, typing, backend tests, frontend tests,
  secret scan, config loading, frontend audit/build, dependency dry-run,
  requirements review, skill validation, generated-artifact cleanup,
  maintainability, API smoke, and frontend smoke.
- `make eval` is the first-class live quality path. It runs `/api/explain` with
  bounded retrieval, parallel case execution, and exact-post cache fallback only
  when the cached prediction URL matches the eval case URL.
- `make eval-cached` is the deterministic no-network proof that the 19 curated
  cases, expected points, citations, fallbacks, and report writers stay stable.
- `make gate7-final-truth-audit` checks docs, requirement rows, GEPA metadata,
  eval counts, branch freshness, and generated-artifact hygiene.

## Live Quality

Live checks must focus on usefulness without becoming an unbounded crawler or
slow benchmark.

- Require a transient `OPENAI_API_KEY` through the environment or masked UI
  field; never write the key to `.env`, docs, reports, or fixtures.
- Keep retrieval bounded through `RETRIEVAL_MAX_QUERIES`,
  `RETRIEVAL_SEARCH_LIMIT_PER_PROVIDER`, and `RETRIEVAL_LINKED_PAGE_LIMIT`.
- Confirm output is English, has 3-5 cited bullets, uses `adapter_mode=none`
  when provider-backed generation succeeds, and exposes trace warnings for
  degraded behavior.
- Run `make live-quality-review` with `OPENAI_API_KEY` when preparing a
  reviewer proof. It writes a curated doc, not raw generated reports, with
  bullets, citations, source counts, latency, fallback mode, and Qdrant status.
- Treat video posts as supported degraded inputs: explain text/thread/link/image
  evidence, keep the request successful, and surface `video_embed_unparsed`.
- Treat image posts as first-class inputs: use OpenAI vision when a key and image
  URL are available, otherwise keep untrusted alt-text fallback visible.
- Regression tests must include weak-answer probes that look superficially valid:
  provider HTTP 200 responses that actually fell back, linked-article answers
  without cited linked/web evidence, marketplace/catalog pages with keyword
  stuffing and inflated runtime quality, deterministic adapter outputs that would
  otherwise pass response-shape checks, missing provider execution traces that
  should never count as live runs, weak live provider rows that should not make a
  provider comparison complete, explicitly ineligible cited sources, provider-
  quality failures that need explicit live-review reasons, aggregate live-review
  rows that are marked passing despite ineligible citations, risky source
  metadata such as prompt-injection flags or failed fetches even when
  `citation_eligible` is missing, provider skip/default warnings that must lower
  provider quality, API attempted rows that must be separated from true live
  successes and not include API-error rows, and provider cost metadata with raw
  fields or secret-like strings that must not leak into reports.

## Reproducible Eval

The cached suite is the stable reviewer proof:

- 19 cases in `eval/posts.yaml`.
- 10 fixture-backed public Bluesky URLs.
- 9 synthetic attack or edge cases.
- Expected key points are the curated truth layer.
- Cached fixtures are allowed only as eval evidence or exact-post fallback for
  the same URL, never as unrelated live-quality proof.

Report fields that must remain visible:

- `public_bluesky_fixture_case_count`
- `synthetic_fixture_case_count`
- `api_attempted_case_count`
- `exact_post_cache_fallback_count`
- `live_prediction_success_count`
- `unsupported_claim_rate`
- `citation_coverage`
- `source_relevance_score`
- `citation_relevance_score`
- `off_topic_source_count`
- `ineligible_citation_count`
- Ragas/DSPy/MLflow skip or run status

## Source Quality And Citations

Source-quality work is tested as a policy, not by manually inspecting every
file touched by retrieval:

- Unit tests score target/thread/quote/image, direct links, fetched web pages,
  snippet-only fallbacks, failed fetches, stale current-event pages, off-topic
  named entities, marketplace/catalog pages, and prompt-injection sources.
- Search and fetch tests require provider, query, rank, canonical domain,
  snippet-only, fetch-success, fetch-status, content type, extracted length, and
  redirect metadata before documents can enter ranking.
- RAG tests force a high-vector off-topic source against a lower-vector
  authoritative source and require the quality-adjusted result to win.
- Guardrail tests verify weak, ineligible, off-topic, single-source, and
  snippet-only evidence downgrades trust before a public answer is accepted.
- Integration tests exercise the live-quality rubric shape with a primary linked
  source plus tempting catalog/snippet evidence and assert only eligible sources
  can become public citations.

## Claim Support And Usefulness

Claim-support checks must prove the answer is useful because it is cited, not
merely because it has citation-looking source IDs:

- Every factual bullet is validated against cited source text for material terms,
  named entities, years/month dates, causal markers, definition markers,
  announcement/passage/confirmation markers, and snippet-only limitations.
- DSPy revisions and final repair both re-run deterministic support checks so a
  revision cannot introduce an unsupported date, entity, or causal explanation.
- Revision and final-repair checks map snippet-only document metadata onto the
  public source IDs that bullets cite, so broad claims cannot hide behind a
  document/source identifier mismatch.
- DSPy validation labels are normalized to the explicit contract before trust
  scoring; non-canonical or typo-shaped model labels cannot silently bypass
  `unsupported_claim`, `weak_citation_support`, `off_topic_citation`,
  `needs_primary_source`, `unsafe_echo`, or `non_english_output` handling.
- Unsafe instruction echoes produce the explicit `unsafe_echo` label in addition
  to legacy leakage labels, and trust scoring treats it as an abstention-level
  risk.
- Live eval source relevance and off-topic checks score cited sources first, so
  weak citations fail while uncited diagnostic sources do not masquerade as
  bullet evidence.
- Source-backed partial fallbacks can count as useful when they preserve
  expected points, citation coverage, source relevance, and safe output; normal
  abstentions remain capped so empty answers do not pass.
- Required regressions include unsupported years, named-entity mismatches,
  causal claims without causal support, snippet-only broad claims, document-ID
  versus source-ID snippet mismatches, non-canonical DSPy validation labels,
  revisions that introduce unsupported facts, uncited catalog diagnostics, and
  linked-post partial summaries when the linked page is unavailable.

## Bonus Surfaces

Image understanding and provider comparison are verified in layers:

- Unit tests cover image coercion, untrusted alt text, vision helper behavior,
  and provider catalog/report generation.
- `make provider-comparison` records configured/skipped provider status.
- `make live-quality-smoke` runs configured providers only when credentials or
  local services are present.
- Missing Anthropic/Gemini/Ollama credentials are config-limited, not a failed
  OpenAI path and not a live multi-provider benchmark.

## Frontend And User Flow

The UI must be tested as the user experiences it:

- `make run` starts Docker UI, API, Qdrant, and MLflow.
- `make dev` starts or reuses source backend/frontend servers in one terminal.
- The form must not reload the page on submit.
- The OpenAI key field must be masked and required for live embeddings/model
  calls.
- Loading state must show the approximate work being done: reading the post,
  searching context, ranking evidence, and writing the English explanation.
- Provider status and skipped reasons must remain visible.

## Regression Priorities

Critical:
- Local startup works with one command.
- API key is required but never committed.
- Live explain returns a schema-valid response with 3-5 cited English bullets or
  an honest fallback.
- Runtime dependency failures return a safe JSON API error envelope instead of
  leaking provider, retrieval, traceback, path, or key details.
- `make eval` cannot hide unrelated live failures behind mismatched fixtures.

High:
- Trace output explicitly reports `qdrant_vector_store` or `in_memory_fallback`
  so reviewers can see whether Qdrant was used or retrieval degraded.
- Reranking remains part of the runtime ranking path.
- Prompt-injection labels preserve post, thread, web, image alt text, and image
  description boundaries.
- Generated reports, Qdrant storage, MLflow runs, screenshots, and provider
  outputs stay ignored.

Medium:
- Maintainability thresholds keep files small enough to review quickly.
- Requirement rows do not overclaim live provider, browser, hosted MLflow, or
  judge behavior.
- Docs use the final truth language: real where integrated, cached where
  reproducibility matters, skipped where credentials/environment are absent,
  partial where helper paths lack full UI/runtime proof.
