# Bluesky Contextual Post Explainer

AI agent for explaining Bluesky posts by finding and synthesizing relevant context.

This repository is being implemented from **Plan Final E**. Gates 0-5 now include
the scaffold, API/domain contracts, real Bluesky fetch, Search/RAG modules,
DSPy/guardrail orchestration, offline eval/reporting, local project skills, a
componentized React UI, and the C5 route integration that wires the lane modules
into one trace-visible runtime path. Gate 6 remains responsible for final
public-post eval expansion and quality review.

## Current Status

- T0 scaffold: implemented.
- Gate 1 requirement matrix: implemented.
- Gate 2 API and domain contracts: implemented.
- Gate 3 vertical slice: implemented with real Bluesky fetch and trace-marked deterministic dev adapters.
- Gate 4 Dev A Backend/API/Bluesky lane: implemented and merged into the integration baseline.
- Gate 4 Dev B Search/RAG/source-safety lane: implemented and merged into the integration baseline.
- Gate 4 Dev C DSPy/guardrails/GEPA/MLflow lane: implemented and merged into the integration baseline.
- Gate 4 Dev D eval/docs lane: implemented with research docs, task packets, local project skills, cached eval fixtures, deterministic metrics, and report generation.
- Gate 4 Dev E frontend lane: implemented and merged into the integration baseline.
- Gate 5 C5 integration: Dev B retrieval is connected into Dev C `AgentExplainerService` through Dev A dependency wiring, Dev E PR #7 polished the C5 response UI, and Dev D records the final review in `docs/reviews/gate5_final_review.md`.
- Image understanding and provider-comparison bonus surfaces remain reserved for their final integration work.
- The assignment API key must be placed only in local `.env`; do not commit it.
- Because the key was shared in plain text during intake, rotate it before real use.
- Current handoff snapshot: `docs/current_handoff.md`.

## Quick Start

```bash
make setup
make deep-review
make requirements-review
make skills-review
make lint
make test
make eval
```

Run the scaffolded services:

```bash
make dev-backend
make dev-frontend
```

The backend exposes `GET /api/health`, `GET /api/providers`, and `POST /api/explain`.
`/api/explain` validates Bluesky post URLs, performs real Bluesky post/thread
fetching, and routes through the C5 integrated Dev B retrieval plus Dev C
agent/guardrail program. When live search, retrieval, DSPy dependencies,
credentials, or provider calls are unavailable, the response remains
schema-valid and records the downgrade in `trace`.

## Frontend UI

The React app runs at `http://localhost:5173` with Vite proxying `/api` to the
FastAPI backend on `http://127.0.0.1:8000`.

The Gate 4 UI includes the Dev E surface from Plan Final E:

- Bluesky post URL form with provider selection from `GET /api/providers`.
- Loading and API error states.
- Cited 3-5 bullet rendering with chips that jump to source cards.
- Source list with title, URL, source type, and snippet.
- Trust/fallback status for `none`, `partial`, `abstain`, and `safe_summary`.
- Guardrail flags and a toggleable trace panel with category, queries,
  warnings, latency, trust score, fallback mode, adapter mode, and notes.

Focused frontend checks:

```bash
npm --prefix frontend test
npm --prefix frontend run build
```

## Environment

```bash
cp .env.example .env
```

Set `OPENAI_API_KEY` in `.env` locally. `.env` is ignored by Git.

## Architecture Target

The final product path is:

```text
Bluesky URL
-> post/thread fetch
-> prompt-injection scan
-> classification
-> query planning
-> Bluesky/web/link/image search
-> sanitization
-> chunk/embed
-> Qdrant retrieve
-> rerank
-> trust scoring
-> cited 3-5 bullet explanation
-> validation
-> guardrail fallback
-> response
```

## API Contract Status

Gate 2 freezes the public response shape for later frontend, eval, and agent
lanes:

```text
POST /api/explain
GET /api/health
GET /api/providers
```

The successful `ExplainResponse` schema already requires 3-5 cited bullets,
sources, and trace fields for trust score, fallback mode, and guardrail flags.
The route now exercises the Dev C agent program, including classification,
query generation, prompt-injection scanning, reranking hooks, trust scoring,
validation, fallback repair, and Dev B Search/RAG retrieval. No-key or provider
failure runs can still downgrade to a cited safe summary or abstain result, and
that downgrade must be visible in the trace.

## Evaluation

`make eval` runs the cached offline evaluation harness. It reads
`eval/posts.yaml` and committed fixtures, performs no network or model calls,
and writes ignored report artifacts under `reports/eval/`:

```text
eval_results.jsonl
eval_report.md
confusion_matrix.csv
metric_bars.svg
summary.json
```

The cached predictions are evaluation fixtures only. They do not replace final
Search/RAG, DSPy, guardrail, or citation behavior.
The current committed cases are synthetic cached fixtures for deterministic
attack and workflow coverage; they are not counted as the final 10+ real public
Bluesky-post eval set. Gate 6 must add or refresh real/fixture-backed public
Bluesky post cases before closing that assignment requirement.

Each report records its prediction mode, judge backend, cached/live row counts,
and whether API or model calls were allowed, so explicit integration runs are
not mislabeled as offline cached runs. Numeric judge outputs, including DSPy
judge scores, are aggregated into `summary.json` and the Markdown report.

The runner has explicit integration modes for later gates:

```bash
cd backend && uv run python -m app.eval.runner --mode fake-agent --judge deterministic
cd backend && uv run python -m app.eval.runner --mode api --judge deterministic
cd backend && uv run --extra ai python -m app.eval.runner --mode cached --judge dspy
cd backend && uv run --extra eval python -m app.eval.runner --mode cached --judge ragas
```

`api` mode requires the local FastAPI app path to be ready for the selected
cases. `dspy` and `ragas` modes require the listed optional extras; when
`OPENAI_API_KEY` is absent they use no-network review paths, and when it is set
they use `dspy_judge_model` for provider-backed judging. The default `make eval`
path stays offline and deterministic for reproducible review.

## Dev C Agent, Guardrails, GEPA, And MLflow

Dev C Gate 4 is implemented under `backend/app/agent/`, `backend/app/guardrails/`,
`backend/app/eval/optimize.py`, and `backend/app/ops/mlflow.py`.

Implemented behavior includes:

- DSPy signatures and live runner wiring for classify, query generation, rerank,
  explain, validate, prompt-injection detection, trust assessment, and eval judge.
- Source-type-specific `UNTRUSTED_*` labels for post, thread, web, and image text.
- Output guardrails for 3-5 bullets, citations, unknown citations, unsafe prompt
  leakage, and schema-valid fallback bullets.
- Trust scoring for low evidence, source diversity, retrieval scores,
  prompt-injection risk, DSPy trust requests, validation failures, and provider
  failures.
- Live DSPy provider/auth/runtime failures degrade to visible guarded fallback
  output instead of crashing `/api/explain`.
- `make optimize` writes GEPA dry-run metadata; `--real` requires valid provider
  credentials, uses a reflection LM, rejects all-failed rollouts, and persists a
  loadable compiled DSPy program directory.
- `make mlflow-log` creates a local MLflow run and exercises
  `mlflow.dspy.log_model` against the live DSPy runner path.

Focused Dev C checks:

```bash
cd backend && uv run pytest app/tests/unit/test_agent_program.py \
  app/tests/unit/test_agent_loader_optimize_mlflow.py \
  app/tests/unit/test_gepa_optimize.py \
  app/tests/unit/test_guardrails.py \
  app/tests/unit/test_prompt_injection_labels.py \
  app/tests/unit/test_agent_output_edges.py
make optimize
make mlflow-log
```

## Integration Adapter Rule

Integration gates must use real Bluesky post fetching. The C5 route attempts the
integrated real Search/RAG and DSPy workflow by default; temporary evidence
sources or deterministic fallbacks are allowed only when live providers,
retrieval, or optional dependencies fail, and any response that uses them must
mark that clearly in `trace`. Public eval completion remains Gate 6 work.

## Commands

```bash
make setup              # install full backend review deps and frontend deps
make setup-backend-full # alias for full backend review deps
make lint               # backend ruff/mypy + frontend TypeScript check
make test               # backend pytest + frontend Vitest
make requirements-review # validate Gate 1 requirement mappings
make skills-review      # validate local project skills
make check-secrets      # verify no tracked env files or obvious API keys
make user-smoke         # exercise backend/frontend as a user-facing scaffold
make eval               # run cached offline eval fixtures and reports
make optimize           # run GEPA dry-run metadata save
make mlflow-log         # create a local MLflow run and package the DSPy program
make deep-review        # full local review gate used before handoff/push
```

## Deep Review Workflow

The registered review gate is:

```bash
make deep-review
```

It runs linting, tests, secret scanning, config validation, frontend audit,
frontend build, optional backend dependency dry-run, requirements matrix
validation, skill validation, maintainability review, and backend/frontend user
smoke tests. The same gate is registered in GitHub Actions at
`.github/workflows/deep-review.yml`.

See `docs/deep_review_workflow.md` for the detailed review checklist.

## Requirement Matrix

`docs/requirements_matrix.md` maps every assignment and Plan Final E requirement
to implementation files, tests or gates, eval artifacts, documentation, and
status. Run:

```bash
make requirements-review
```

The final submission cannot be considered complete unless this gate passes and
all rows have moved from planned or reserved to implemented where required.

## Security

- Never commit `.env`.
- Never commit API keys.
- Never commit `mlruns/`, Qdrant cache, or live generated artifacts.
- All external content is treated as untrusted evidence, never as instructions.

## Handoff Spine

Research docs live under `docs/research/`, task packets live at
`docs/task_packets.md`, and local project skills live under `.codex/skills/`.
Run `make skills-review` or each skill's local `quick_validate.py` before
handoff.
The next implementation step should replace the temporary thread-context
evidence path with Dev B Search/RAG while preserving Dev C guardrails and trace
semantics.
