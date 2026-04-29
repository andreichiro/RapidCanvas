# Bluesky Contextual Post Explainer

AI agent for explaining Bluesky posts by finding and synthesizing relevant context.

This repository is being implemented from **Plan Final E**. T0 establishes a safe,
working project scaffold: backend package metadata, frontend package metadata,
command surface, secret handling, README skeleton, and translation log.

## Current Status

- T0 scaffold: implemented.
- T1-T15: planned next phases.
- The assignment API key must be placed only in local `.env`; do not commit it.
- Because the key was shared in plain text during intake, rotate it before real use.

## Quick Start

```bash
make setup
make deep-review
make lint
make test
```

Run the scaffolded services:

```bash
make dev-backend
make dev-frontend
```

The backend scaffold exposes `GET /api/health`. The full `/api/explain` contract
will be implemented in T2/T3.

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

## Commands

```bash
make setup              # install backend dev deps and frontend deps
make setup-backend-full # install optional backend deps for later phases
make lint               # backend ruff/mypy + frontend TypeScript check
make test               # backend pytest + frontend Vitest
make check-secrets      # verify no tracked env files or obvious API keys
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
frontend build, optional backend dependency dry-run, and an API health smoke
test. The same gate is registered in GitHub Actions at
`.github/workflows/deep-review.yml`.

See `docs/deep_review_workflow.md` for the detailed review checklist.

## Security

- Never commit `.env`.
- Never commit API keys.
- Never commit `mlruns/`, Qdrant cache, or live generated artifacts.
- All external content will be treated as untrusted evidence in later phases.

## Next Phase

T1 creates research docs, project skills, `AGENTS.md`, `docs/task_packets.md`,
and the full requirement matrix.
