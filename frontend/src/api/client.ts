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
  api_key?: string;
};

type ApiErrorPayload = {
  detail?: string | { message?: string } | Array<{ msg?: string; message?: string }>;
};

class ApiHttpError extends Error {}

const LOCAL_BACKEND_BASE_URL = "http://127.0.0.1:8000";

function configuredApiBaseUrl(): string | null {
  const env = import.meta.env as { VITE_API_BASE_URL?: string };
  const configured = env.VITE_API_BASE_URL?.trim();
  return configured ? configured.replace(/\/+$/, "") : null;
}

function localApiBases(): string[] {
  const configured = configuredApiBaseUrl();
  if (configured) {
    return [configured];
  }

  if (typeof window === "undefined") {
    return [""];
  }

  const bases = [""];
  const isBackendOrigin =
    ["localhost", "127.0.0.1"].includes(window.location.hostname) && window.location.port === "8000";
  if (!isBackendOrigin) {
    bases.push(LOCAL_BACKEND_BASE_URL);
  }
  return bases;
}

function apiUrl(baseUrl: string, path: string): string {
  return baseUrl ? `${baseUrl}${path}` : path;
}

function isJsonResponse(response: Response): boolean {
  return (response.headers.get("Content-Type") ?? "").toLowerCase().includes("application/json");
}

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

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const bases = localApiBases();
  let lastError: Error | null = null;

  for (const [index, baseUrl] of bases.entries()) {
    const isLast = index === bases.length - 1;
    try {
      const response = await fetch(apiUrl(baseUrl, path), init);
      if (!response.ok) {
        const error = new ApiHttpError(await readError(response));
        if (!isLast && response.status === 404) {
          lastError = error;
          continue;
        }
        throw error;
      }
      if (!isJsonResponse(response)) {
        const error = new Error("The API server did not return JSON.");
        if (!isLast) {
          lastError = error;
          continue;
        }
        throw error;
      }
      return (await response.json()) as T;
    } catch (caught) {
      if (caught instanceof ApiHttpError) {
        throw caught;
      }
      const error = caught instanceof Error ? caught : new Error("Unable to reach the API server.");
      if (!isLast) {
        lastError = error;
        continue;
      }
      throw new Error(
        `${error.message} Confirm FastAPI is running at ${LOCAL_BACKEND_BASE_URL} or set VITE_API_BASE_URL.`
      );
    }
  }

  throw lastError ?? new Error(`Unable to reach the API server at ${LOCAL_BACKEND_BASE_URL}.`);
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  const payload = await requestJson<{ providers: ProviderInfo[] }>("/api/providers");
  return payload.providers;
}

export async function explainPost(request: ExplainRequest): Promise<ExplainResponse> {
  return requestJson<ExplainResponse>("/api/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
}
