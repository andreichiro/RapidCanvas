# Deep Review Workflow

This workflow is the registered review gate for the RapidCanvas repository.
It is available locally through `make deep-review` and in GitHub Actions through
`.github/workflows/deep-review.yml`.

## Local Command

```bash
make deep-review
```

## What It Checks

1. Backend linting and typing:

   ```bash
   cd backend && uv run ruff check app && uv run mypy app
   ```

2. Frontend typing:

   ```bash
   npm --prefix frontend run lint
   ```

3. Backend tests:

   ```bash
   cd backend && uv run pytest app/tests
   ```

4. Frontend tests:

   ```bash
   npm --prefix frontend test
   ```

5. Secret hygiene:

   ```bash
   make check-secrets
   ```

6. Backend config load and JSON validity:

   ```bash
   cd backend && uv run python -m app.config
   ```

7. Frontend dependency audit:

   ```bash
   npm --prefix frontend audit --audit-level=moderate
   ```

8. Frontend production build:

   ```bash
   npm --prefix frontend run build
   ```

9. Optional backend dependency resolvability:

   ```bash
   cd backend && uv sync --dev --all-extras --dry-run
   ```

10. Backend API smoke test:

    ```bash
    uvicorn app.main:app
    curl http://127.0.0.1:8001/api/health
    ```

## Manual Review Checklist

Use this checklist for advanced human or agent review:

- Verify no `.env`, API key, `mlruns/`, Qdrant cache, `frontend/dist/`, or live generated report is tracked.
- Verify `.env.example` contains placeholders only.
- Verify `TRANSLATION_LOG.md` records assumptions and workflow changes.
- Verify README describes the current implementation honestly.
- Verify later-phase commands fail clearly if not implemented.
- Verify no background `uvicorn`, `vite`, or `mlflow` process remains after smoke tests.
- Verify generated TypeScript metadata and build outputs are ignored.
- Verify optional heavy dependencies resolve without being installed during normal T0 setup.

## Acceptance Rule

T0 is accepted only when `make deep-review` passes locally and the GitHub
Actions `Deep Review` workflow is registered for pushes and pull requests.

