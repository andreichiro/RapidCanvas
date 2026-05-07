# Deep Review Workflow

This workflow is the registered review gate for the RapidCanvas repository.
It is available locally through `make deep-review` and in GitHub Actions through
`.github/workflows/deep-review.yml`. GitHub Actions also runs
`make eval-cached` after the deep review gate so cached quality drift is caught
before handoff.

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

10. Requirement matrix completeness:

    ```bash
    make requirements-review
    ```

    This verifies Gate 1 has every required assignment and plan row, each row has
    implementation, test, eval, documentation, and status mappings, and no row
    has a missing mapping.

11. Project skill validation:

    ```bash
    make skills-review
    ```

    This verifies each local project skill has `SKILL.md`, `agents/openai.yaml`,
    references, required metadata, and a working skill-local `quick_validate.py`
    entry point.

12. Generated artifact cleanup:

    ```bash
    make clean-generated
    ```

13. Backend API smoke test:

    ```bash
    uvicorn app.main:app
    curl http://127.0.0.1:8001/api/health
    ```

14. Maintainability review:

    ```bash
    python3 scripts/review_quality.py
    ```

    This checks handoff docs, command discoverability, generated artifact
    hygiene, reserved-command honesty, file/function size, placeholder markers,
    and whether the user-facing scaffold text matches the current plan.

15. Frontend user smoke test:

    ```bash
    make frontend-smoke
    ```

    This starts Vite and verifies the browser-facing scaffold shell is served.

## Manual Review Checklist

Use this checklist for advanced human or agent review:

- Verify no `.env`, API key, `mlruns/`, Qdrant cache, `frontend/dist/`, or live generated report is tracked.
- Verify `.env.example` contains placeholders only.
- Verify `docs/current_handoff.md` reflects the current gate, boundaries, and next work.
- Verify `TRANSLATION_LOG.md` records assumptions and workflow changes.
- Verify `docs/requirements_matrix.md` maps every assignment and Plan Final E requirement.
- Verify `make skills-review` and skill-local `quick_validate.py` entry points pass.
- Verify README describes the current implementation honestly.
- Verify later-phase commands fail clearly if not implemented.
- Verify no background `uvicorn`, `vite`, or `mlflow` process remains after smoke tests.
- Verify generated TypeScript metadata and build outputs are ignored.
- Verify full review dependencies install through `make setup`, and keep any
  additional generated dependency artifacts ignored.
- Verify code is easy to understand, easy to maintain, easy to change, easy to explain, and free of unnecessary complexity.
- Verify user-facing behavior with browser-use when local UI work changes.

## Acceptance Rule

The current scaffold gates are accepted only when `make deep-review` passes
locally and the GitHub Actions `Deep Review` workflow is registered for pushes
and pull requests. Manual provider-backed live quality runs belong in
`.github/workflows/live-eval.yml`, which requires the repository
`OPENAI_API_KEY` secret and uploads ignored report artifacts.
