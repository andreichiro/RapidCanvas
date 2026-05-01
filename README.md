# Bluesky Contextual Post Explainer

RapidCanvas is a React + FastAPI + DSPy agent that accepts a public Bluesky post URL,
searches for relevant context, and returns 3-5 cited explanation bullets. The reviewer
entry points are this README, the requirement matrix, the cached eval report, and the
Gate 7 final truth review.

## What It Does

- Fetches the target Bluesky post and thread context from public read-only AT Protocol APIs.
- Plans lightweight context queries from the post, thread, links, category, and available image text.
- Searches Bluesky/web/link context, sanitizes untrusted text, embeds/chunks evidence, retrieves with Qdrant or an in-memory fallback, reranks, and validates citations.
- Produces 3-5 bullets with source IDs for normal answers, or `partial`, `safe_summary`, or `abstain` when support is weak.
- Shows sources, trust/fallback status, guardrail flags, and trace diagnostics in the React UI.
- Requires a masked OpenAI key at request time so embeddings and model-backed explanations run without committing secrets.

## Run Locally

The full-stack one-command path is Docker:

```bash
make run
```

Open `http://localhost:5173`, paste a public Bluesky post URL, paste your OpenAI key
into the masked field, leave provider as `openai`, and click **Explain**.

`make run` starts the React UI, FastAPI backend, Qdrant, and MLflow UI. It does
not hardcode or bake in API keys.

For source development without Docker:

```bash
make setup
make dev
```

`make dev` starts FastAPI at `http://127.0.0.1:8000` and Vite at
`http://localhost:5173` in one terminal. The frontend first uses the Vite `/api`
proxy and then falls back to `http://127.0.0.1:8000` so preview/local launches do
not fail with a generic browser `Failed to fetch` when the backend is running.

Useful direct checks:

```bash
curl http://127.0.0.1:8000/api/health
npm --prefix frontend test
make test
make eval
make gate7-final-truth-audit
```

## Docker

For a clean machine with Docker:

```bash
make run
```

Then open `http://localhost:5173`. The Compose stack starts:

- FastAPI backend: `http://127.0.0.1:8000`
- React UI: `http://localhost:5173`
- Qdrant: `http://localhost:6333`
- MLflow UI: `http://localhost:5000`

The backend receives `QDRANT_URL=http://qdrant:6333` and
`MLFLOW_TRACKING_URI=http://mlflow:5000`; no API keys are baked into images or Compose.
Stop it with:

```bash
make docker-down
```

## API Key Handling

The UI has a masked required OpenAI API-key field. The key is sent only with the
current `/api/explain` request as `api_key`; it is not written to local storage, `.env`,
reports, or Git. CLI/headless runs may also use a local ignored `.env`:

```bash
cp .env.example .env
# set OPENAI_API_KEY in .env only if you want CLI requests to use it
```

The default backend route rejects keyless explain requests when no local
`OPENAI_API_KEY` exists. This prevents a no-key setup from silently looking successful
while only returning conservative fallback answers.

## Architecture

```text
Bluesky URL
-> public post/thread fetch
-> prompt-injection scan
-> classification
-> query planning
-> Bluesky/web/link/image context search
-> sanitization
-> chunk/embed
-> Qdrant or in-memory retrieval
-> rerank
-> trust scoring
-> cited 3-5 bullet explanation
-> validation
-> guardrail fallback
-> response
```

The Gate 7 runtime uses one-shot Search/RAG by default. The capped adaptive retrieval is enabled path
allows at most one extra safe query when first-round evidence is weak, it
stops early when trust is sufficient, and it is skipped after pre-retrieval
prompt-injection risk. The agent does not perform unbounded searching until confidence
is high.

## Frontend

The React UI includes:

- Bluesky URL input.
- Masked required OpenAI API-key input.
- Provider selector populated by `GET /api/providers`.
- 3-5 cited bullet rendering.
- Source cards and citation chips.
- Trust/fallback badge for `none`, `partial`, `safe_summary`, and `abstain`.
- Guardrail flags.
- Trace panel with category, queries, diagnostics, latency, trust score, fallback mode,
  adapter mode, and notes.

Common retrieval diagnostics are summarized as retrieval notes instead of presented as
hard failures. For example, Qdrant fallback, content truncation, HTTP 403 source pages,
empty extracted pages, and Bluesky search outages are non-fatal when other evidence is
available. Full raw diagnostics remain in the trace panel for review.

## Backend API

```text
GET  /api/health
GET  /api/providers
POST /api/explain
```

`POST /api/explain` accepts:

```json
{
  "post_url": "https://bsky.app/profile/{actor}/post/{rkey}",
  "provider": "openai",
  "include_trace": true,
  "api_key": "sk-..."
}
```

Responses include post metadata, cited bullets, source cards, and trace data. Invalid
URLs return clean 422 errors. Upstream Bluesky/read failures return sanitized errors or
guarded fallbacks; external content is treated as evidence, never instructions.

## Deep Review Workflow

`make deep-review` is the full pre-handoff gate. It runs linting, tests, secret
scanning, config validation, frontend audit/build, optional backend dependency checks,
Gate 1 requirement review, local skill validation, generated-artifact cleanup,
maintainability review, and user smoke tests.

## Evaluation

`make eval` is the reproducible quality proof. It runs offline against cached fixtures
and writes ignored reports under `reports/eval/`:

```text
eval_results.jsonl
eval_report.md
confusion_matrix.csv
metric_bars.svg
summary.json
```

Gate 6/Gate 7 eval status:

- 19 cached cases.
- 10 fixture-backed public Bluesky URLs.
- 9 marked synthetic attack/edge fixtures.
- No network or model calls in default `make eval`.
- Expected key points are the curated truth layer.
- Live Search/RAG is runtime retrieval and data collection, not ground truth.

The eval harness measures expected-point recall, citation coverage, fallback
correctness, prompt-injection resistance, unsupported/hallucination counts, source
support, private URL blocking, and latency. Optional DSPy/Ragas judge modes are explicit
commands, not the default no-network gate.

## GEPA And MLflow

`make optimize` verifies the merged GEPA saved-program path. The final artifact is a
real compiled saved DSPy program from finalized cached eval fixtures:

```text
backend/app/agent/optimized/program.json
backend/app/agent/optimized/program_compiled/
```

`program.json` records `mode=real`, `metric_score=0.875`, and a 19-case eval-dataset
bridge. Loader use still depends on DSPy and provider credentials.

`make mlflow-log` creates a local file-backed MLflow run and exercises
`mlflow.dspy.log_model`. This is real local ops plumbing, not a hosted experiment
workflow. `mlruns/` is ignored.

## Image And Providers

Image understanding is included as Bluesky image URL/alt-text context plus a helper-level
OpenAI vision path with untrusted alt-text fallback. A live helper smoke described a
public image in 3.3s, but this was not a full browser/UI vision proof, so the final
truth classification remains partial.

Provider comparison is visible through `GET /api/providers` and the UI provider selector.
OpenAI can run with the transient request key. Anthropic, Gemini, and Ollama are listed
with configured/skipped status and skipped reasons, but this is not a live
multi-provider benchmark unless those provider credentials/services are configured and
an explicit comparison run is performed.

## Guardrails

- Every normal factual answer must have 3-5 bullets.
- Every factual bullet must cite at least one source.
- Low evidence, contradictions, provider failures, unavailable posts, uncited claims, or
  unsafe content produce `partial`, `safe_summary`, or `abstain`.
- Posts, replies, web pages, image alt text, and image descriptions are labeled
  `UNTRUSTED_*` inside prompts.
- Prompt-injection attempts are scanned and ignored as instructions.
- Only public Bluesky reads, safe web GETs, embeddings/model/vision calls, and optional
  provider calls are reachable. No Bluesky write APIs are exposed.

## Commands

```bash
make setup                    # install backend and frontend dependencies
make run                      # one-command Docker UI + API + Qdrant + MLflow
make dev                      # one-command local backend + frontend
make docker-up                # one-command Docker UI + API + Qdrant + MLflow
make docker-down              # stop Docker stack
make lint                     # backend ruff/mypy + frontend TypeScript
make test                     # backend pytest + frontend Vitest
make eval                     # cached offline eval reports
make optimize                 # GEPA saved-program verification
make mlflow-log               # local MLflow run/package path
make requirements-review      # requirement matrix validation
make skills-review            # local skill validation
make check-secrets            # secret/artifact hygiene scan
make gate7-final-truth-audit  # final truth audit
make deep-review              # full local review gate
```

## Submission Truth

Gate 1 is closed by `docs/requirements_matrix.md` and `make requirements-review`.
The final review is `docs/reviews/gate7_final_review.md`; the closure proof is
`docs/requirements_matrix.md`; the concise status handoff is `docs/current_handoff.md`.

This submission is real where integrated, cached where reproducibility matters, skipped
where credentials/environment are absent, partial where helper/runtime paths exist
without full UI proof, and reserved where behavior is not implemented, tested,
documented, and visible in reports.

Security reminder: `.env`, API keys, `mlruns/`, Qdrant cache, screenshots, provider
outputs, and generated live reports must not be committed.
