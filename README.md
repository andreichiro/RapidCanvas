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
- T1-T15: planned next phases.
- The assignment API key must be placed only in local `.env`; do not commit it.
- Because the key was shared in plain text during intake, rotate it before real use.

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

The backend exposes `GET /api/health`, `GET /api/providers`, and the frozen
`POST /api/explain` contract. `/api/explain` validates Bluesky post URLs and
returns `501` until the real Bluesky/search/DSPy pipeline is implemented, so no
fake explanation is presented as product behavior.

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
The route intentionally returns `501` until the real pipeline is available.

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
handoff spine. Gate 3 is the vertical slice that connects the frozen API shape
to the first implementation path without claiming mocks as final behavior.
