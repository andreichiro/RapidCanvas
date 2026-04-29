# Frontend React Vite Research

## Source links
- Vite guide: https://vite.dev/guide/
- Vite React plugin: https://github.com/vitejs/vite-plugin-react
- Vitest docs: https://vitest.dev/
- React Testing Library intro: https://testing-library.com/docs/react-testing-library/intro/

## Exact syntax snippets
```ts
const response = await fetch("/api/explain", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({post_url, provider, include_trace: true}),
});
```

```ts
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
```

## Selected default
- Vite + React + TypeScript with Vitest and Testing Library.
- Components render URL input, provider selector, cited bullets, source list, trust/fallback badge, guardrail flags, trace toggle, loading, and error states.
- Browser-use verification records visible UI behavior in `TRANSLATION_LOG.md`.

## Rejected alternatives
- Do not build a marketing landing page before the usable explainer.
- Do not hard-code final API behavior in the UI.
- Do not hide adapter or fallback status from the user.

## Implementation consequence
Dev E can consume the frozen `ExplainResponse` while Dev D eval reports verify citation/source/trace fields that the UI must display.

