export type Bullet = {
  text: string;
  source_ids: string[];
};

export type Source = {
  id: string;
  title: string;
  url: string;
  type: "thread" | "bluesky" | "web" | "image";
  snippet: string;
  quality_score?: number | null;
  quality_reasons?: string[];
  citation_eligible?: boolean | null;
};

export type Trace = {
  request_id?: string | null;
  provider?: string | null;
  vector_store_backend?: string | null;
  category: string;
  queries: string[];
  warnings: string[];
  latency_ms: number;
  trust_score: number;
  fallback_mode: "none" | "partial" | "abstain" | "safe_summary";
  guardrail_flags: string[];
  adapter_mode: "none" | "deterministic_fallback";
  adapter_notes: string[];
  source_quality?: Array<Record<string, unknown>>;
  image_status?: Array<Record<string, unknown>>;
  live_quality_notes?: string[];
};

export type ExplainResponse = {
  post: {
    url: string;
    author: string;
    text: string;
    created_at: string;
  };
  bullets: Bullet[];
  sources: Source[];
  trace: Trace;
};

export type ProviderInfo = {
  name: string;
  configured: boolean;
  skipped_reason: string | null;
  runnable: boolean;
  default_model: string | null;
  comparison_status: "ran" | "skipped" | "configured_not_run" | null;
};

export type ExplainRequest = {
  post_url: string;
  provider: string;
  include_trace: boolean;
  api_key?: string;
};
