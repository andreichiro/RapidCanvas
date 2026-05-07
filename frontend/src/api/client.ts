import { parseExplainResponse, parseProvidersResponse } from "./validation";

export type { Bullet, ExplainRequest, ExplainResponse, ProviderInfo, Source, Trace } from "./types";
import { type ExplainRequest, type ExplainResponse, type ProviderInfo } from "./types";

type ApiErrorPayload = {
  code?: string;
  error?: string;
  detail?:
    | string
    | { code?: string; error?: string; message?: string; details?: string[]; reason?: string }
    | Array<{ msg?: string; message?: string; type?: string }>;
  message?: string;
};

type ParsedApiError = {
  code?: string;
  details: string[];
  message: string;
};

export class ApiRequestError extends Error {
  code?: string;
  details: string[];
  status?: number;

  constructor(message: string, options: { code?: string; details?: string[]; status?: number } = {}) {
    super(message);
    this.name = "ApiRequestError";
    this.code = options.code;
    this.details = options.details ?? [];
    this.status = options.status;
  }
}

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

async function readStructuredError(response: Response): Promise<ParsedApiError> {
  const fallback = response.statusText || `Request failed with status ${response.status}.`;

  try {
    const payload = (await response.json()) as ApiErrorPayload;
    const code = payload.code ?? payload.error;
    if (typeof payload.message === "string" && payload.message.trim()) {
      return { code, details: [], message: payload.message.trim() };
    }
    if (typeof payload.detail === "string") {
      return { code, details: [], message: payload.detail };
    }
    if (Array.isArray(payload.detail)) {
      const details = payload.detail.map((item) => item.message ?? item.msg).filter(isString);
      const detailCode = payload.detail.find((item) => typeof item.type === "string")?.type;
      return { code: code ?? detailCode, details, message: details.join("; ") || fallback };
    }
    if (payload.detail) {
      const detailCode = payload.detail.code ?? payload.detail.error;
      const details = Array.isArray(payload.detail.details) ? payload.detail.details.filter(isString) : [];
      return {
        code: code ?? detailCode,
        details,
        message: payload.detail.message ?? payload.detail.reason ?? fallback,
      };
    }
    return { code, details: [], message: fallback };
  } catch {
    return { details: [], message: fallback };
  }
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const bases = localApiBases();
  let lastError: Error | null = null;

  for (const [index, baseUrl] of bases.entries()) {
    const isLast = index === bases.length - 1;
    try {
      if (init?.signal?.aborted) {
        throw new DOMException("The operation was aborted.", "AbortError");
      }
      const response = await fetch(apiUrl(baseUrl, path), init);
      if (!response.ok) {
        const parsedError = await readStructuredError(response);
        const error = new ApiRequestError(parsedError.message, {
          code: parsedError.code,
          details: parsedError.details,
          status: response.status,
        });
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
      if (caught instanceof ApiRequestError) {
        throw caught;
      }
      const error = caught instanceof Error ? caught : new Error("Unable to reach the API server.");
      if (init?.signal?.aborted) {
        throw error;
      }
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
  const payload = await requestJson<unknown>("/api/providers");
  return parseProvidersResponse(payload);
}

export async function explainPost(request: ExplainRequest, signal?: AbortSignal): Promise<ExplainResponse> {
  const payload = await requestJson<unknown>("/api/explain", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify(request),
  });
  return parseExplainResponse(payload);
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}
