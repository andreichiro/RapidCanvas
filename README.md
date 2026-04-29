# Bluesky Contextual Post Explainer

AI agent for explaining Bluesky posts by finding and synthesizing relevant context.

This repository is being implemented from **Plan Final E**. T0 establishes a safe,
working project scaffold: backend package metadata, frontend package metadata,
command surface, secret handling, README skeleton, and translation log. Gate 1
adds the requirement matrix and validates assignment coverage in the review gate.

## Current Status

- T0 scaffold: implemented.
- Gate 1 requirement matrix: implemented.
- Gate 2 API and domain contracts: implemented.
- Gate 3 vertical slice: implemented with real Bluesky fetch and trace-marked deterministic dev adapters.
- T1-T15: planned next phases.
- The assignment API key must be placed only in local `.env`; do not commit it.
- Because the key was shared in plain text during intake, rotate it before real use.
- Current handoff snapshot: `docs/current_handoff.md`.

## Quick Start

```bash
make setup
make deep-review
make requirements-review
make lint
make test
```

Run the scaffolded services:

```bash
make dev-backend
make dev-frontend
```

The backend exposes `GET /api/health`, `GET /api/providers`, and `POST /api/explain`.
`/api/explain` validates Bluesky post URLs, performs real Bluesky post/thread
fetching, and returns a schema-valid safe summary. Search/RAG and DSPy are still
deterministic dev adapters and are marked in `trace`.

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
The route now returns a Gate 3 vertical-slice response. It is not the final
contextual explainer because Search/RAG and DSPy are trace-marked deterministic
dev adapters.

## Integration Adapter Rule

Future integration gates must use real Bluesky post fetching. Search/RAG and
DSPy may use temporary deterministic dev adapters only while their real modules
are incomplete, and any response that uses such adapters must mark that clearly
in `trace`. Those adapters are not accepted as final implementation and cannot
satisfy requirement-matrix rows. Final acceptance requires real Search/RAG, real
DSPy workflow, real citations, real trust/fallback behavior, and real eval.

## Commands

```bash
make setup              # install backend dev deps and frontend deps
make setup-backend-full # install optional backend deps for later phases
make lint               # backend ruff/mypy + frontend TypeScript check
make test               # backend pytest + frontend Vitest
make requirements-review # validate Gate 1 requirement mappings
make check-secrets      # verify no tracked env files or obvious API keys
make user-smoke         # exercise backend/frontend as a user-facing scaffold
make deep-review        # full local review gate used before handoff/push
```

Later-phase commands are reserved now and intentionally fail until implemented:

```bash
make eval
make optimize
make mlflow-log
```

## Deep Review Workflow

The registered review gate is:

```bash
make deep-review
```

It runs linting, tests, secret scanning, config validation, frontend audit,
frontend build, optional backend dependency dry-run, requirements matrix
validation, maintainability review, and backend/frontend user smoke tests. The
same gate is registered in GitHub Actions at `.github/workflows/deep-review.yml`.

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
- All external content will be treated as untrusted evidence in later phases.

## Next Phase

T1 research docs, project skills, and `docs/task_packets.md` remain part of the
handoff spine. The next implementation replacement should remove the Gate 3
Search/RAG and DSPy adapters only when real modules and tests are ready.
