# Live Quality Review

This is the committed reviewer-facing live proof surface. It is intentionally
small and curated instead of committing raw generated reports.

## How To Refresh

```bash
OPENAI_API_KEY=... make live-quality-review
```

The command runs six fixture-backed public Bluesky URLs through the real FastAPI
`/api/explain` route with bounded retrieval limits, then overwrites this file
with a table containing:

- input URL and case id;
- status code and latency;
- returned bullet count and source count;
- fallback mode;
- Qdrant status: `qdrant_vector_store`, `in_memory_fallback`, or `not_reported`;
- whether the answer was meaningful by the reviewer smoke rule;
- returned bullets and cited source ids.

The OpenAI key is supplied locally through `OPENAI_API_KEY` and is never written
to this file.

## Meaningful Smoke Rule

A live row is marked meaningful only when all of these are true:

- HTTP status is 200;
- response has 3-5 bullets;
- every bullet has citations;
- at least one source is returned;
- fallback mode is not `abstain`;
- adapter mode is `none`.

This does not replace a broad benchmark. It gives reviewers a fast, reproducible
way to prove the current live path is useful on real public Bluesky inputs.

## Latest Committed Status

This file is a refresh target. The last full local verification in this branch
passed without `OPENAI_API_KEY` in the shell, so live rows were not regenerated
in this commit. The broader review gate still passed through `make deep-review`,
`make eval-cached`, `make provider-comparison`, `make optimize`,
`make mlflow-log`, and `make check-secrets`.
