import { type Bullet, type ExplainResponse, type ProviderInfo, type Source, type Trace } from "./types";

const LEGACY_ADAPTER_MODE = ["deterministic", "dev"].join("_");

type RawTrace = Omit<Trace, "adapter_mode"> & {
  adapter_mode: Trace["adapter_mode"] | string;
};

type RawExplainResponse = Omit<ExplainResponse, "trace"> & {
  trace: RawTrace;
};

export function parseExplainResponse(payload: unknown): ExplainResponse {
  if (!isExplainResponseShape(payload)) {
    throw new Error("API response did not match the explanation contract.");
  }
  return {
    post: payload.post,
    bullets: payload.bullets,
    sources: payload.sources.map(normalizeSource),
    trace: normalizeTrace(payload.trace),
  };
}

export function parseProvidersResponse(payload: unknown): ProviderInfo[] {
  if (!isRecord(payload) || !Array.isArray(payload.providers)) {
    throw new Error("API provider response did not match the provider contract.");
  }
  return payload.providers.map((item) => {
    if (!isProviderInfoShape(item)) {
      throw new Error("API provider response did not match the provider contract.");
    }
    return normalizeProviderInfo(item);
  });
}

function isExplainResponseShape(payload: unknown): payload is RawExplainResponse {
  if (!isRecord(payload)) {
    return false;
  }
  return (
    isPost(payload.post) &&
    isArrayOf(payload.bullets, isBullet) &&
    payload.bullets.length >= 3 &&
    payload.bullets.length <= 5 &&
    isArrayOf(payload.sources, isSource) &&
    payload.sources.length >= 1 &&
    isTrace(payload.trace)
  );
}

function isPost(value: unknown): value is ExplainResponse["post"] {
  return (
    isRecord(value) &&
    isString(value.url) &&
    isString(value.author) &&
    isString(value.text) &&
    isString(value.created_at)
  );
}

function isBullet(value: unknown): value is Bullet {
  return isRecord(value) && isString(value.text) && isArrayOf(value.source_ids, isString);
}

function isSource(value: unknown): value is Source {
  return (
    isRecord(value) &&
    isString(value.id) &&
    isString(value.title) &&
    isString(value.url) &&
    isSourceType(value.type) &&
    isString(value.snippet) &&
    isOptionalNumberOrNull(value.quality_score) &&
    isOptionalArrayOf(value.quality_reasons, isString) &&
    isOptionalBooleanOrNull(value.citation_eligible)
  );
}

function isTrace(value: unknown): value is RawTrace {
  return (
    isRecord(value) &&
    isString(value.category) &&
    isArrayOf(value.queries, isString) &&
    isArrayOf(value.warnings, isString) &&
    isNumber(value.latency_ms) &&
    isNumber(value.trust_score) &&
    isFallbackMode(value.fallback_mode) &&
    isArrayOf(value.guardrail_flags, isString) &&
    isAdapterModeLike(value.adapter_mode) &&
    isArrayOf(value.adapter_notes, isString) &&
    isOptionalStringOrNull(value.request_id) &&
    isOptionalStringOrNull(value.provider) &&
    isOptionalStringOrNull(value.vector_store_backend) &&
    isOptionalArrayOf(value.source_quality, isRecord) &&
    isOptionalArrayOf(value.image_status, isRecord) &&
    isOptionalArrayOf(value.live_quality_notes, isString)
  );
}

function isSourceType(value: unknown): value is Source["type"] {
  return value === "thread" || value === "bluesky" || value === "web" || value === "image";
}

function isFallbackMode(value: unknown): value is Trace["fallback_mode"] {
  return value === "none" || value === "partial" || value === "abstain" || value === "safe_summary";
}

function isAdapterMode(value: unknown): value is Trace["adapter_mode"] {
  return value === "none" || value === "deterministic_fallback";
}

function isAdapterModeLike(value: unknown): boolean {
  return isAdapterMode(value) || value === LEGACY_ADAPTER_MODE;
}

function isProviderInfoShape(value: unknown): value is ProviderInfo {
  return (
    isRecord(value) &&
    isString(value.name) &&
    isBoolean(value.configured) &&
    isOptionalStringOrNull(value.skipped_reason) &&
    isOptionalBoolean(value.runnable) &&
    isOptionalStringOrNull(value.default_model) &&
    isOptionalComparisonStatus(value.comparison_status)
  );
}

function normalizeProviderInfo(provider: ProviderInfo): ProviderInfo {
  return {
    name: provider.name,
    configured: provider.configured,
    skipped_reason: provider.skipped_reason ?? null,
    runnable: provider.runnable ?? false,
    default_model: provider.default_model ?? null,
    comparison_status: provider.comparison_status ?? null,
  };
}

function normalizeSource(source: Source): Source {
  return {
    ...source,
    citation_eligible: source.citation_eligible ?? null,
    quality_reasons: source.quality_reasons ?? [],
    quality_score: source.quality_score ?? null,
  };
}

function normalizeTrace(trace: RawTrace): Trace {
  return {
    ...trace,
    adapter_mode:
      trace.adapter_mode === LEGACY_ADAPTER_MODE
        ? "deterministic_fallback"
        : (trace.adapter_mode as Trace["adapter_mode"]),
    image_status: trace.image_status ?? [],
    live_quality_notes: trace.live_quality_notes ?? [],
    provider: trace.provider ?? null,
    request_id: trace.request_id ?? null,
    source_quality: trace.source_quality ?? [],
    vector_store_backend: trace.vector_store_backend ?? null,
  };
}

function isOptionalArrayOf<T>(value: unknown, guard: (item: unknown) => item is T): value is T[] | undefined {
  return value === undefined || isArrayOf(value, guard);
}

function isOptionalBoolean(value: unknown): value is boolean | undefined {
  return value === undefined || isBoolean(value);
}

function isOptionalBooleanOrNull(value: unknown): value is boolean | null | undefined {
  return value === undefined || value === null || isBoolean(value);
}

function isOptionalComparisonStatus(value: unknown): value is ProviderInfo["comparison_status"] | undefined {
  return (
    value === undefined ||
    value === null ||
    value === "ran" ||
    value === "skipped" ||
    value === "configured_not_run"
  );
}

function isOptionalNumberOrNull(value: unknown): value is number | null | undefined {
  return value === undefined || value === null || isNumber(value);
}

function isOptionalStringOrNull(value: unknown): value is string | null | undefined {
  return value === undefined || value === null || isString(value);
}

function isArrayOf<T>(value: unknown, guard: (item: unknown) => item is T): value is T[] {
  return Array.isArray(value) && value.every(guard);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}
