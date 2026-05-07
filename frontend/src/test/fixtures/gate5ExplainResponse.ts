import { type ExplainResponse, type Trace } from "../../api/client";

export const gate5ExplainResponse: ExplainResponse = {
  post: {
    url: "https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y",
    author: "bsky.app",
    text: "We hear and appreciate your feedback on the photo carousel. We're going to put it back in the oven for now.",
    created_at: "2026-04-23T17:06:32Z",
  },
  bullets: [
    {
      text: "Bluesky says the photo carousel is paused while the team revisits the rollout.",
      source_ids: ["thread-post", "bluesky-context"],
    },
    {
      text: "The post leaves open a return for posts with more than four photos or videos.",
      source_ids: ["thread-post", "web-result"],
    },
    {
      text: "Image evidence is treated as supporting context rather than a separate conclusion.",
      source_ids: ["image-context", "thread-post"],
    },
    {
      text: "Retrieval notes should remain visible without changing the backend's trust decision.",
      source_ids: ["web-result"],
    },
  ],
  sources: [
    {
      id: "thread-post",
      title: "Thread context from Bluesky",
      url: "https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y",
      type: "thread",
      snippet: "Photo carousel feedback is acknowledged in the original post.",
      quality_score: 0.96,
      quality_reasons: ["target post context"],
      citation_eligible: true,
    },
    {
      id: "bluesky-context",
      title: "Bluesky reply context",
      url: "https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y/replies",
      type: "bluesky",
      snippet: "Replies discuss how the carousel affected post presentation.",
      quality_score: 0.84,
      quality_reasons: ["thread context"],
      citation_eligible: true,
    },
    {
      id: "web-result",
      title: "External coverage of image carousel feedback",
      url: "https://example.com/bluesky-carousel-feedback",
      type: "web",
      snippet: "Coverage summarizes user feedback and planned changes.",
      quality_score: 0.72,
      quality_reasons: ["fetched web page"],
      citation_eligible: true,
    },
    {
      id: "image-context",
      title: "Attached image metadata",
      url: "https://cdn.example.com/carousel-preview.png",
      type: "image",
      snippet: "Image metadata describes a carousel preview attachment.",
      quality_score: 0.78,
      quality_reasons: ["image metadata"],
      citation_eligible: true,
    },
  ],
  trace: {
    request_id: "req-gate5-fixture",
    provider: "openai",
    vector_store_backend: "in_memory_fallback",
    category: "product_change",
    queries: [
      "bluesky photo carousel rollout feedback",
      "long retrieval query with multiple quoted terms and source filters that should wrap cleanly inside the trace panel",
      "photo carousel more than four photos videos support",
    ],
    warnings: [
      "retrieval warning: one search result was skipped because the source was unavailable during reranking",
      "low evidence warning: fewer than three independent evidence chunks were available",
    ],
    latency_ms: 238,
    trust_score: 0.84,
    fallback_mode: "none",
    guardrail_flags: [],
    adapter_mode: "deterministic_fallback",
    adapter_notes: ["openai/gpt-4.1-mini was used by the integrated explainer service"],
    source_quality: [
      {
        source_id: "web-result",
        quality_score: 0.72,
        citation_eligible: true,
      },
    ],
    image_status: [
      {
        image_index: 1,
        image_evidence_role: "supporting_context",
        vision_used: false,
        alt_text_used: true,
      },
    ],
    live_quality_notes: ["fixture response"],
  },
};

export function gate5ResponseWithTrace(trace: Partial<Trace>): ExplainResponse {
  return {
    ...gate5ExplainResponse,
    trace: {
      ...gate5ExplainResponse.trace,
      ...trace,
    },
  };
}
