import { type Source } from "../api/client";
import { sourceAnchorId } from "./sourceAnchors";

type SourceListProps = {
  sources: Source[];
};

function readableType(type: Source["type"]): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

function qualityScoreLabel(score: Source["quality_score"]): string {
  if (typeof score !== "number") {
    return "Quality not reported";
  }
  return `Quality ${Math.round(score * 100)}%`;
}

function citationEligibilityLabel(source: Source): string {
  if (source.citation_eligible === true) {
    return "Citation eligible";
  }
  if (source.citation_eligible === false) {
    return "Citation blocked";
  }
  return "Citation eligibility not reported";
}

export default function SourceList({ sources }: SourceListProps) {
  return (
    <section className="source-list" aria-label="sources">
      <h2>Sources</h2>
      <div className="source-grid">
        {sources.map((source) => (
          <article id={sourceAnchorId(source.id)} key={source.id} className="source-card">
            <div className="source-card-header">
              <strong>{source.id}</strong>
              <span>{readableType(source.type)}</span>
            </div>
            <div className="source-quality-row" aria-label={`source quality ${source.id}`}>
              <span>{qualityScoreLabel(source.quality_score)}</span>
              <span>{citationEligibilityLabel(source)}</span>
            </div>
            {source.quality_reasons?.length ? (
              <ul className="source-quality-reasons">
                {source.quality_reasons.map((reason, index) => (
                  <li key={`${reason}-${index}`}>{reason}</li>
                ))}
              </ul>
            ) : null}
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.title}
            </a>
            <a className="source-url" href={source.url} target="_blank" rel="noreferrer">
              {source.url}
            </a>
            <p>{source.snippet}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
