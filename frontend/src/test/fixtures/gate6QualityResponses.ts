import { type ExplainResponse, type Trace } from "../../api/client";

type Gate6TracePatch = Partial<Trace>;

const baseTrace: Trace = {
  category: "gate6_quality_smoke",
  queries: [
    "bluesky context quality smoke",
    "source support for cited explanation",
    "guardrail fallback evidence",
  ],
  warnings: [],
  latency_ms: 184,
  trust_score: 0.86,
  fallback_mode: "none",
  guardrail_flags: [],
  adapter_mode: "none",
  adapter_notes: [],
};

export const gate6NormalResponse: ExplainResponse = {
  post: {
    url: "https://bsky.app/profile/example.com/post/3gate6normal",
    author: "example.com",
    text: "What is this launch drama about?",
    created_at: "2026-05-01T13:15:00Z",
  },
  bullets: [
    {
      text: "The post is reacting to a launch announcement and asks why the response has been so mixed.",
      source_ids: ["S-post", "S-thread"],
    },
    {
      text: "Thread replies add that the confusion is mostly about rollout timing and feature availability.",
      source_ids: ["S-thread"],
    },
    {
      text: "External coverage confirms that the rollout is staged, which explains why some users see different behavior.",
      source_ids: ["S-web"],
    },
    {
      text: "The attached image is supporting context only and does not change the explanation by itself.",
      source_ids: ["S-image", "S-post"],
    },
  ],
  sources: [
    {
      id: "S-post",
      title: "Original Bluesky post",
      url: "https://bsky.app/profile/example.com/post/3gate6normal",
      type: "thread",
      snippet: "What is this launch drama about?",
    },
    {
      id: "S-thread",
      title: "Reply context",
      url: "https://bsky.app/profile/example.com/post/3gate6normal/replies",
      type: "bluesky",
      snippet: "Replies discuss rollout timing and feature availability.",
    },
    {
      id: "S-web",
      title: "Launch coverage",
      url: "https://example.com/launch-coverage",
      type: "web",
      snippet: "Coverage describes a staged launch and user-facing availability differences.",
    },
    {
      id: "S-image",
      title: "Screenshot attachment",
      url: "https://cdn.example.com/launch-screenshot.png",
      type: "image",
      snippet: "Screenshot shows the launch banner that users are discussing.",
    },
  ],
  trace: baseTrace,
};

export function gate6ResponseWithTrace(trace: Gate6TracePatch): ExplainResponse {
  return {
    ...gate6NormalResponse,
    trace: {
      ...gate6NormalResponse.trace,
      ...trace,
    },
  };
}

export const gate6PartialResponse = gate6ResponseWithTrace({
  trust_score: 0.48,
  fallback_mode: "partial",
  warnings: ["low evidence warning: only two independent evidence chunks support broader context"],
  guardrail_flags: ["low_evidence"],
});

export const gate6AbstainResponse = gate6ResponseWithTrace({
  trust_score: 0.07,
  fallback_mode: "abstain",
  warnings: ["unavailable_or_deleted: the referenced Bluesky post could not be fetched from the public API"],
  guardrail_flags: ["post_unavailable", "low_evidence"],
});

export const gate6SafeSummaryResponse = gate6ResponseWithTrace({
  trust_score: 0.31,
  fallback_mode: "safe_summary",
  warnings: ["provider_upstream_error: DSPy provider failed, so only visible post context was summarized"],
  guardrail_flags: ["dspy_provider_error"],
  adapter_mode: "deterministic_dev",
  adapter_notes: ["Provider fallback was trace-marked by the backend."],
});

export const gate6PromptInjectionResponse = gate6ResponseWithTrace({
  trust_score: 0.42,
  fallback_mode: "partial",
  warnings: ["prompt_injection_risk: untrusted source attempted to disable citations"],
  guardrail_flags: ["prompt_injection_risk", "disable_citations"],
});

export const gate6ContradictoryResponse = gate6ResponseWithTrace({
  trust_score: 0.39,
  fallback_mode: "partial",
  warnings: ["contradictory_sources: retrieved sources disagree about the launch timing"],
  guardrail_flags: ["conflicting_sources"],
});

export const gate6LowTrustResponse = gate6ResponseWithTrace({
  trust_score: 0.18,
  fallback_mode: "partial",
  warnings: ["low_trust: retrieval scores were below the backend trust threshold"],
  guardrail_flags: ["low_evidence", "weak_retrieval_score"],
});
