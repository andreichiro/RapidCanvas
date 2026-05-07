import { useMemo, useState } from "react";

import { type ExplainResponse } from "../api/client";
import CitationChip from "./CitationChip";
import GuardrailFlags from "./GuardrailFlags";
import SourceList from "./SourceList";
import TracePanel from "./TracePanel";
import TrustBadge from "./TrustBadge";

type ResultViewProps = {
  result: ExplainResponse;
};

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

function fallbackCopy(mode: ExplainResponse["trace"]["fallback_mode"]): string | null {
  if (mode === "partial") {
    return "Only supported points are shown.";
  }
  if (mode === "abstain") {
    return "Evidence was not sufficient for a contextual explanation.";
  }
  if (mode === "safe_summary") {
    return "The answer is limited to visible post and thread context.";
  }
  return null;
}

function code(...parts: string[]): string {
  return parts.join("_");
}

function readableTraceValue(value: string): string {
  return value.replaceAll("_", " ");
}

function formatBooleanLabel(label: string, value: unknown): string | null {
  if (typeof value !== "boolean") {
    return null;
  }
  return `${label} ${value ? "yes" : "no"}`;
}

function formatRecordValue(value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (Array.isArray(value)) {
    return value.map(formatRecordValue).filter(Boolean).join(", ") || null;
  }
  if (typeof value === "boolean") {
    return value ? "yes" : "no";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  return String(value);
}

function runtimeSummary(trace: ExplainResponse["trace"]): Array<{ label: string; value: string }> {
  return [
    trace.provider ? { label: "Provider", value: trace.provider } : null,
    trace.vector_store_backend ? { label: "Vector backend", value: readableTraceValue(trace.vector_store_backend) } : null,
    trace.request_id ? { label: "Request ID", value: trace.request_id } : null,
  ].filter((item): item is { label: string; value: string } => Boolean(item));
}

function imageEvidenceSummary(trace: ExplainResponse["trace"]): string[] {
  const imageIndexKey = code("image", "index");
  const imageEvidenceRoleKey = code("image", "evidence", "role");
  const visionUsedKey = code("vision", "used");
  const altTextUsedKey = code("alt", "text", "used");
  const visionWarningKey = code("vision", "warning");
  const promptInjectionFlagsKey = code("prompt", "injection", "flags");

  const images = (trace.image_status ?? []).map((status, index) => {
    const imageNumber = formatRecordValue(status[imageIndexKey]) ?? String(index + 1);
    const role = formatRecordValue(status[imageEvidenceRoleKey] ?? status.role ?? status.status);
    const parts = [
      `Image ${imageNumber}`,
      role ? readableTraceValue(role) : null,
      formatBooleanLabel("vision", status[visionUsedKey]),
      formatBooleanLabel("alt text", status[altTextUsedKey]),
      formatRecordValue(status[visionWarningKey]),
      formatRecordValue(status[promptInjectionFlagsKey]),
    ].filter(Boolean);
    return parts.join(" - ");
  });

  const hasVideoWarning = trace.warnings.some((warning) => warning.startsWith("video_embed_unparsed"));
  return hasVideoWarning
    ? [
        ...images,
        "Video evidence: video frames are not parsed; this explanation uses text, thread, link, and image evidence only.",
      ]
    : images;
}

function warningSummary(warnings: string[]): string[] {
  const optimizedProgramLoaded = code("optimized", "program", "loaded");
  const optimizedDspyProgramLoaded = code("optimized", "dspy", "program", "loaded");
  const qdrantMemoryFallback = code("qdrant", "unavailable", "using", "in", "memory", "vector", "store");
  const qdrantVectorStore = code("qdrant", "vector", "store");
  const inMemoryFallback = code("in", "memory", "fallback");
  const blueskySearchFailed = code("bluesky", "search", "failed");
  const contentTruncated = code("content", "truncated");
  const emptyExtractedText = code("empty", "extracted", "text");

  const mapped = warnings
    .map((warning) => {
      if (warning === optimizedProgramLoaded || warning === optimizedDspyProgramLoaded) {
        return null;
      }
      if (warning === qdrantVectorStore) {
        return "Qdrant vector search was used for this request.";
      }
      if (warning === inMemoryFallback) {
        return "Qdrant was not used; this request used the in-memory retriever.";
      }
      if (warning.startsWith(qdrantMemoryFallback)) {
        return "Vector database was unavailable, so this request used the in-memory retriever.";
      }
      if (warning.startsWith(blueskySearchFailed)) {
        return "Bluesky search was unavailable, so the answer used other retrieved sources when possible.";
      }
      if (warning === contentTruncated) {
        return "Some long source content was truncated before retrieval.";
      }
      if (warning.startsWith("http_status:403")) {
        return "One source page denied access with HTTP 403.";
      }
      if (warning === emptyExtractedText) {
        return "One fetched source did not expose readable text.";
      }
      if (warning.startsWith("video_embed_unparsed")) {
        return "This post contains a video; the explanation uses text, thread, link, and image evidence without parsing video frames.";
      }
      return warning;
    })
    .filter((warning): warning is string => Boolean(warning));

  return Array.from(new Set(mapped));
}

export default function ResultView({ result }: ResultViewProps) {
  const [traceOpen, setTraceOpen] = useState(false);
  const sourcesById = useMemo(
    () => new Map(result.sources.map((source) => [source.id, source])),
    [result.sources],
  );
  const fallbackMessage = fallbackCopy(result.trace.fallback_mode);
  const visibleWarnings = warningSummary(result.trace.warnings);
  const runtimeItems = runtimeSummary(result.trace);
  const visualEvidence = imageEvidenceSummary(result.trace);

  return (
    <section className={`result-view fallback-${result.trace.fallback_mode}`} aria-label="explanation result">
      <header className="post-summary">
        <div>
          <span className="label-text">Original post</span>
          <h2>{result.post.author}</h2>
          <a className="post-link" href={result.post.url} target="_blank" rel="noreferrer">
            Open post
          </a>
        </div>
        <time dateTime={result.post.created_at}>{formatDate(result.post.created_at)}</time>
      </header>

      <details className="post-original">
        <summary>Original post text (author's language)</summary>
        <p className="post-text">{result.post.text || "No post text returned."}</p>
      </details>

      <div className="status-strip">
        <TrustBadge fallbackMode={result.trace.fallback_mode} trustScore={result.trace.trust_score} />
        <GuardrailFlags flags={result.trace.guardrail_flags} />
      </div>

      {runtimeItems.length ? (
        <dl className="runtime-summary" aria-label="runtime summary">
          {runtimeItems.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {fallbackMessage ? (
        <div className="fallback-banner" role="status">
          {fallbackMessage}
        </div>
      ) : null}

      {visibleWarnings.length ? (
        <section className="trace-warning-summary" aria-label="warnings">
          <h2>Retrieval notes</h2>
          <ul>
            {visibleWarnings.map((warning, index) => (
              <li key={`${warning}-${index}`}>{warning}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {visualEvidence.length ? (
        <section className="visual-evidence-summary" aria-label="image and video evidence">
          <h2>Image and video evidence</h2>
          <ul>
            {visualEvidence.map((item, index) => (
              <li key={`${item}-${index}`}>{item}</li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="explanation-section" aria-labelledby="english-explanation-heading">
        <h2 id="english-explanation-heading">English explanation</h2>
        <ol className="bullets" aria-label="explanation bullets">
          {result.bullets.map((bullet, index) => (
            <li key={`${bullet.text}-${index}`}>
              <span>{bullet.text}</span>
              <span className="citation-row" aria-label={`citations for bullet ${index + 1}`}>
                {bullet.source_ids.map((sourceId, sourceIndex) => (
                  <CitationChip key={`${sourceId}-${sourceIndex}`} source={sourcesById.get(sourceId)} sourceId={sourceId} />
                ))}
              </span>
            </li>
          ))}
        </ol>
      </section>

      <SourceList sources={result.sources} />
      <TracePanel isOpen={traceOpen} onToggle={() => setTraceOpen((value) => !value)} trace={result.trace} />
    </section>
  );
}
