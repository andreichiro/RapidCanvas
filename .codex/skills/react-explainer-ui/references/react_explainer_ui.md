# React Explainer UI Notes

Expected components:
- `UrlForm`
- `ProviderSelect`
- `ResultView`
- `CitationChip`
- `SourceList`
- `TracePanel`
- `ErrorBanner`
- `TrustBadge`
- `GuardrailFlags`

```ts
await fetch("/api/explain", {
  method: "POST",
  headers: {"Content-Type": "application/json"},
  body: JSON.stringify({post_url, provider, include_trace: true}),
});
```

Tests should cover submit, success, citations, trace toggle, trust/fallback display, error state, and abstain state.

