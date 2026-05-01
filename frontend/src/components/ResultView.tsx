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

function warningSummary(warnings: string[]): string[] {
  const optimizedProgramLoaded = code("optimized", "program", "loaded");
  const optimizedDspyProgramLoaded = code("optimized", "dspy", "program", "loaded");
  const qdrantMemoryFallback = code("qdrant", "unavailable", "using", "in", "memory", "vector", "store");
  const blueskySearchFailed = code("bluesky", "search", "failed");
  const contentTruncated = code("content", "truncated");
  const emptyExtractedText = code("empty", "extracted", "text");

  const mapped = warnings
    .map((warning) => {
      if (warning === optimizedProgramLoaded || warning === optimizedDspyProgramLoaded) {
        return null;
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

  return (
    <section className={`result-view fallback-${result.trace.fallback_mode}`} aria-label="explanation result">
      <header className="post-summary">
        <div>
          <span className="label-text">Post</span>
          <h2>{result.post.author}</h2>
          <a className="post-link" href={result.post.url} target="_blank" rel="noreferrer">
            Open post
          </a>
        </div>
        <time dateTime={result.post.created_at}>{formatDate(result.post.created_at)}</time>
      </header>

      <p className="post-text">{result.post.text || "No post text returned."}</p>

      <div className="status-strip">
        <TrustBadge fallbackMode={result.trace.fallback_mode} trustScore={result.trace.trust_score} />
        <GuardrailFlags flags={result.trace.guardrail_flags} />
      </div>

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

      <SourceList sources={result.sources} />
      <TracePanel isOpen={traceOpen} onToggle={() => setTraceOpen((value) => !value)} trace={result.trace} />
    </section>
  );
}
