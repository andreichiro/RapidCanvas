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

export default function ResultView({ result }: ResultViewProps) {
  const [traceOpen, setTraceOpen] = useState(false);
  const sourcesById = useMemo(
    () => new Map(result.sources.map((source) => [source.id, source])),
    [result.sources],
  );
  const fallbackMessage = fallbackCopy(result.trace.fallback_mode);

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

      {result.trace.warnings.length ? (
        <section className="trace-warning-summary" aria-label="warnings">
          <h2>Warnings</h2>
          <ul>
            {result.trace.warnings.map((warning, index) => (
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
