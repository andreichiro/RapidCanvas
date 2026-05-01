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
};

export type Trace = {
  category: string;
  queries: string[];
  warnings: string[];
  latency_ms: number;
  trust_score: number;
  fallback_mode: "none" | "partial" | "abstain" | "safe_summary";
  guardrail_flags: string[];
  adapter_mode: "none" | "deterministic_dev";
  adapter_notes: string[];
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
  default_model: string | null;
};

export type ExplainRequest = {
  post_url: string;
  provider: string;
  include_trace: boolean;
};

type ApiErrorPayload = {
  detail?: string | { message?: string } | Array<{ msg?: string; message?: string }>;
};

async function readError(response: Response): Promise<string> {
  const fallback = response.statusText || `Request failed with status ${response.status}.`;

  try {
    const payload = (await response.json()) as ApiErrorPayload;
    if (typeof payload.detail === "string") {
      return payload.detail;
    }
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.message ?? item.msg).filter(Boolean).join("; ") || fallback;
    }
    return payload.detail?.message ?? fallback;
  } catch {
    return fallback;
  }
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const response = await fetch("/api/providers");
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  const payload = (await response.json()) as { providers: ProviderInfo[] };
  return payload.providers;
}

export async function explainPost(request: ExplainRequest): Promise<ExplainResponse> {
  const response = await fetch("/api/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw new Error(await readError(response));
  }
  return (await response.json()) as ExplainResponse;
}
