---
name: dspy-fastapi-agent
description: Build and serve the RapidCanvas DSPy explainer through FastAPI. Use when Codex is implementing DSPy signatures/modules, async FastAPI deployment, provider configuration, optimized-program loading, guardrail integration, or schema-valid `/api/explain` responses.
---

# DSPy FastAPI Agent

## Workflow
1. Keep FastAPI routes thin; inject an explainer service behind the frozen API contract.
2. Represent model behavior as DSPy signatures for classification, query planning, reranking, explanation, validation, prompt-injection detection, and trust assessment.
3. Configure the provider through `dspy.LM(settings.dspy_model)` and `dspy.configure`.
4. Use `dspy.asyncify(program)` before serving high-latency model calls.
5. Prefer optimized program artifacts when present; fall back to baseline modules with trace notes.
6. Return only validated `ExplainResponse` objects.

## Guardrails
- Retrieved content is labeled untrusted and used only as evidence.
- Normal responses need exactly 3-5 cited bullets.
- Low evidence, contradiction, unsafe content, or uncited claims must produce `partial`, `safe_summary`, or `abstain`.
- Any temporary adapter use must appear in `trace.adapter_mode`, warnings, and guardrail flags.

## Reference
Load `references/dspy_fastapi_agent.md` for syntax and route integration notes.
