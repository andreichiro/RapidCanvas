import { type Source } from "../api/client";

type SourceListProps = {
  sources: Source[];
};

function readableType(type: Source["type"]): string {
  return type.charAt(0).toUpperCase() + type.slice(1);
}

export default function SourceList({ sources }: SourceListProps) {
  return (
    <section className="source-list" aria-label="sources">
      <h2>Sources</h2>
      <div className="source-grid">
        {sources.map((source) => (
          <article id={`source-${source.id}`} key={source.id} className="source-card">
            <div className="source-card-header">
              <strong>{source.id}</strong>
              <span>{readableType(source.type)}</span>
            </div>
            <a href={source.url} target="_blank" rel="noreferrer">
              {source.title}
            </a>
            <p>{source.snippet}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
