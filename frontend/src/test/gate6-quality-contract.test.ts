import { expect, test } from "vitest";

import { type ExplainResponse } from "../api/client";
import appSource from "../App.tsx?raw";
import apiClientSource from "../api/client.ts?raw";
import citationChipSource from "../components/CitationChip.tsx?raw";
import errorBannerSource from "../components/ErrorBanner.tsx?raw";
import guardrailFlagsSource from "../components/GuardrailFlags.tsx?raw";
import providerSelectSource from "../components/ProviderSelect.tsx?raw";
import resultViewSource from "../components/ResultView.tsx?raw";
import sourceAnchorsSource from "../components/sourceAnchors.ts?raw";
import sourceListSource from "../components/SourceList.tsx?raw";
import tracePanelSource from "../components/TracePanel.tsx?raw";
import trustBadgeSource from "../components/TrustBadge.tsx?raw";
import urlFormSource from "../components/UrlForm.tsx?raw";
import mainSource from "../main.tsx?raw";
import { sourceAnchorId } from "../components/sourceAnchors";
import handoffSource from "../../GATE6_UI_HANDOFF.md?raw";
import {
  gate6AbstainResponse,
  gate6ContradictoryResponse,
  gate6LowTrustResponse,
  gate6NormalResponse,
  gate6PartialResponse,
  gate6PromptInjectionResponse,
  gate6SafeSummaryResponse,
} from "./fixtures/gate6QualityResponses";

const gate6Responses: ExplainResponse[] = [
  gate6NormalResponse,
  gate6PartialResponse,
  gate6AbstainResponse,
  gate6SafeSummaryResponse,
  gate6PromptInjectionResponse,
  gate6ContradictoryResponse,
  gate6LowTrustResponse,
];

const productionSourceFiles: Array<{ path: string; text: string }> = [
  { path: "App.tsx", text: appSource },
  { path: "api/client.ts", text: apiClientSource },
  { path: "components/CitationChip.tsx", text: citationChipSource },
  { path: "components/ErrorBanner.tsx", text: errorBannerSource },
  { path: "components/GuardrailFlags.tsx", text: guardrailFlagsSource },
  { path: "components/ProviderSelect.tsx", text: providerSelectSource },
  { path: "components/ResultView.tsx", text: resultViewSource },
  { path: "components/sourceAnchors.ts", text: sourceAnchorsSource },
  { path: "components/SourceList.tsx", text: sourceListSource },
  { path: "components/TracePanel.tsx", text: tracePanelSource },
  { path: "components/TrustBadge.tsx", text: trustBadgeSource },
  { path: "components/UrlForm.tsx", text: urlFormSource },
  { path: "main.tsx", text: mainSource },
];

test("Gate 6 fixture responses stay inside the public API contract shape", () => {
  for (const response of gate6Responses) {
    expect(response.bullets.length).toBeGreaterThanOrEqual(3);
    expect(response.bullets.length).toBeLessThanOrEqual(5);

    const sourceIds = new Set(response.sources.map((source) => source.id));
    expect(sourceIds.size).toBe(response.sources.length);
    for (const bullet of response.bullets) {
      expect(bullet.source_ids.length).toBeGreaterThan(0);
      for (const sourceId of bullet.source_ids) {
        expect(sourceIds.has(sourceId)).toBe(true);
      }
    }

    expect(response.trace.category).toEqual(expect.any(String));
    expect(response.trace.queries).toEqual(expect.any(Array));
    expect(response.trace.warnings).toEqual(expect.any(Array));
    expect(response.trace.latency_ms).toEqual(expect.any(Number));
    expect(response.trace.trust_score).toEqual(expect.any(Number));
    expect(["none", "partial", "abstain", "safe_summary"]).toContain(response.trace.fallback_mode);
    expect(response.trace.guardrail_flags).toEqual(expect.any(Array));
    expect(["none", "deterministic_dev"]).toContain(response.trace.adapter_mode);
    expect(response.trace.adapter_notes).toEqual(expect.any(Array));
  }
});

test("Gate 6 fixtures cover the required frontend quality states", () => {
  expect(gate6NormalResponse.trace.fallback_mode).toBe("none");
  expect(gate6PartialResponse.trace.fallback_mode).toBe("partial");
  expect(gate6AbstainResponse.trace.fallback_mode).toBe("abstain");
  expect(gate6SafeSummaryResponse.trace.fallback_mode).toBe("safe_summary");
  expect(gate6PromptInjectionResponse.trace.guardrail_flags).toContain("prompt_injection_risk");
  expect(gate6ContradictoryResponse.trace.guardrail_flags).toContain("conflicting_sources");
  expect(gate6LowTrustResponse.trace.guardrail_flags).toContain("low_evidence");
});

test("production frontend code renders backend quality fields without making quality decisions", () => {
  const trustDecisionPattern = /\b(?:trust_score|trustScore)\b\s*(?:[<>]=?|={2,3}|!={1,2})/;
  const backendFlagLiteralPattern =
    /\b(?:low_evidence|prompt_injection_risk|conflicting_sources|weak_retrieval_score|dspy_provider_error|post_unavailable|disable_citations|provider_upstream_error)\b/;
  const allowedSchemaSnakeCaseLiterals = new Set(["deterministic_dev", "fallback_mode", "safe_summary"]);
  const snakeCaseStringLiteralPattern = /["'`]([a-z]+(?:_[a-z]+)+)["'`]/g;

  const trustDecisionFiles = productionSourceFiles
    .filter((file) => trustDecisionPattern.test(file.text))
    .map((file) => file.path);
  expect(trustDecisionFiles).toEqual([]);

  const flagDecisionFiles = productionSourceFiles
    .filter((file) => backendFlagLiteralPattern.test(file.text))
    .map((file) => file.path);
  expect(flagDecisionFiles).toEqual([]);

  const unexpectedSnakeCaseLiterals = productionSourceFiles.flatMap((file) =>
    Array.from(file.text.matchAll(snakeCaseStringLiteralPattern))
      .map((match) => match[1])
      .filter((literal) => !allowedSchemaSnakeCaseLiterals.has(literal))
      .map((literal) => `${file.path}: ${literal}`),
  );
  expect(unexpectedSnakeCaseLiterals).toEqual([]);
});

test("fallback states use backend-provided modes for visual classes without deriving new quality states", () => {
  expect(resultViewSource).toContain("fallback-${result.trace.fallback_mode}");
});

test("citation chips and source cards share encoded backend source-id anchors", () => {
  expect(sourceAnchorId("S weird/#1")).toBe("source-S%20weird%2F%231");
  expect(sourceAnchorsSource).toContain("encodeURIComponent(sourceId)");
  expect(citationChipSource).toContain("sourceAnchorId(sourceId)");
  expect(sourceListSource).toContain("sourceAnchorId(source.id)");
});

test("Gate 6 UI handoff stays useful for final integration review", () => {
  for (const requiredText of [
    "does not add frontend-only",
    "Normal explanation",
    "Partial fallback",
    "Abstain fallback",
    "Safe-summary fallback",
    "Prompt-injection warning",
    "Contradictory-source warning",
    "Low-trust warning",
    "Unavailable/deleted post API error banner",
    "Provider/upstream API error banner",
    "Citation chips link to source card ids",
    "Trace panel displays category",
    "fixture-shaped states",
    "Dev D selected public Gate 6 cases were not available",
    "Case-selection note for Dev D",
    "API shape risk for Dev A",
  ]) {
    expect(handoffSource).toContain(requiredText);
  }
});
