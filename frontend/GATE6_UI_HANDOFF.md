# Gate 6 UI Handoff

Dev E scope: prove users can understand backend quality, fallback, citation,
source, trace, warning, and error states. This lane does not add frontend-only
trust scoring, fallback decisions, citation validation, or guardrail logic.

## Verified States

- Normal explanation with 4 cited bullets and source cards.
- Partial fallback with low-evidence warning and guardrail flag.
- Abstain fallback with unavailable/low-evidence flags.
- Safe-summary fallback with provider-error guardrail flag.
- Prompt-injection warning and `prompt_injection_risk`/`disable_citations`
  guardrail flags.
- Contradictory-source warning and `conflicting_sources` guardrail flag.
- Low-trust warning with backend-provided trust score.
- Unavailable/deleted post API error banner.
- Provider/upstream API error banner.
- FastAPI validation detail array error banner.
- Citation chips link to source card ids.
- Citation/source anchors remain linkable when backend source ids contain spaces,
  slashes, or hash-like characters.
- Trace panel displays category, queries, warnings, latency, trust score,
  fallback mode, guardrail flags, adapter mode, and adapter notes.
- Automated contract checks verify fixture citation/source integrity and scan
  production UI source for frontend-only quality decisions.

## Fixtures Used

- Frontend unit fixtures:
  `frontend/src/test/fixtures/gate6QualityResponses.ts`.
- Automated frontend tests:
  `frontend/src/test/gate6-quality-response.test.tsx` and
  `frontend/src/test/gate6-quality-contract.test.ts`.
- Browser verification fixture API:
  a local untracked stub server on `http://127.0.0.1:8000` returning the stable
  public `ExplainResponse` shape through Vite's normal `/api` proxy.

Dev D selected public Gate 6 cases were not available in this branch at the time
of this Dev E pass, so browser verification used closest fixture-shaped states.
Final case-matched browser verification should be repeated after Dev D publishes
the representative case set.

## Browser-Use Checks

Browser-use opened the real Vite UI at `http://127.0.0.1:5173/` and submitted
fixture URLs through the normal form. It checked:

- normal explanation bullets, citation chip `S-web`, source card `Launch coverage`;
- encoded citation/source fragment for a source id containing spaces and
  punctuation, including click-through to the matching `:target` source card;
- trace panel category/latency/trust fields;
- partial fallback and low-evidence flag;
- abstain fallback and post-unavailable flag;
- safe-summary fallback and provider-error guardrail flag;
- prompt-injection warning and guardrail flag;
- contradictory-source warning and flag;
- unavailable/deleted post error banner;
- provider/upstream error banner;
- FastAPI validation detail array banner;
- browser console errors: none observed.

## Automated Review Strategy

- Critical: `gate6-quality-contract.test.ts` fails if production UI/API-client
  TS/TSX source starts comparing trust scores or hard-coding backend guardrail
  flag names, which would create frontend-only quality decisions.
- Critical: the same test rejects unexpected snake_case string literals in
  production UI source so new backend-looking quality flags cannot be hard-coded
  without explicitly classifying them as schema values.
- High: the same contract test fails if Gate 6 fixtures drift outside the public
  API shape, lose 3-5 bullets, duplicate source ids, or cite missing source ids.
- High: response rendering tests fail if citation chips and source cards stop
  sharing a deterministic fragment id for backend-provided source ids that need
  URL-fragment encoding.
- Medium: response rendering tests fail if normal, fallback, warning, source,
  citation, trace label, unavailable/deleted, provider-error, or validation-error
  states stop being visible to users.
- Medium: response rendering tests require distinct fallback visual classes, and
  CSS wraps long trace list items so diagnostic strings remain scannable instead
  of overflowing the trace panel.

No screenshots, reports, live artifacts, `.env`, Qdrant cache, or `mlruns`
artifacts were added.

## Notes For Dev A And Dev D

- API shape risk for Dev A: frontend currently expects `trace.adapter_mode` and
  `trace.adapter_notes` to be present because the Dev A Gate 6 baseline schema
  includes defaults for both fields.
- Case-selection note for Dev D: include at least one public/cached case that
  produces each frontend-smoked state so final review evidence can replace the
  fixture-only browser pass.
- UI limitation: the trace panel intentionally renders backend diagnostic values
  verbatim. Very long values wrap and the panel scrolls; the UI does not
  summarize or reinterpret them.
