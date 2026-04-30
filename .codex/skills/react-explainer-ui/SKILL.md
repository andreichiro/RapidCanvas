---
name: react-explainer-ui
description: Build the React interface for the RapidCanvas Bluesky explainer. Use when Codex is implementing URL submission, provider selection, cited bullets, source lists, citation chips, trust/fallback display, guardrail flags, trace panels, errors, loading states, or browser verification for the frontend.
---

# React Explainer UI

## Workflow
1. Keep the first screen as the usable explainer, not a landing page.
2. Submit `post_url`, `provider`, and `include_trace` to `/api/explain`.
3. Render exactly the response contract: post summary, 3-5 bullets, source citation chips, source list, and trace.
4. Make fallback states visually clear: `partial`, `safe_summary`, and `abstain`.
5. Display guardrail flags and adapter status honestly.
6. Verify with Vitest and browser-use against localhost after meaningful UI changes.

## UI Expectations
- Provider selector uses `/api/providers`.
- Citation chips link to corresponding source entries.
- Trace panel is toggled and includes category, queries, warnings, latency, trust score, fallback mode, and guardrail flags.
- Error and loading states are explicit and do not shift the layout unexpectedly.

## Reference
Load `references/react_explainer_ui.md` for API types and expected components.
