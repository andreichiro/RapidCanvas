import { FormEvent, useEffect, useState } from "react";

import { ExplainResponse, ProviderInfo, explainPost, fetchProviders } from "./api/client";

const SAMPLE_URL = "https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y";

type RequestState = "idle" | "loading" | "success" | "error";

export default function App() {
  const [postUrl, setPostUrl] = useState(SAMPLE_URL);
  const [provider, setProvider] = useState("openai");
  const [providers, setProviders] = useState<ProviderInfo[]>([]);
  const [result, setResult] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [showTrace, setShowTrace] = useState(false);

  useEffect(() => {
    fetchProviders()
      .then(setProviders)
      .catch(() => {
        setProviders([{ name: "openai", configured: false, skipped_reason: null, default_model: null }]);
      });
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRequestState("loading");
    setError(null);
    setResult(null);
    try {
      const response = await explainPost({
        post_url: postUrl,
        provider,
        include_trace: true,
      });
      setResult(response);
      setRequestState("success");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to explain this post.");
      setRequestState("error");
    }
  }

  return (
    <main className="app-shell">
      <section className="workspace" aria-labelledby="app-title">
        <p className="eyebrow">Gate 3 vertical slice; T0 scaffold preserved</p>
        <h1 id="app-title">Bluesky Contextual Post Explainer</h1>
        <p>
          Real Bluesky fetch is wired through the API. Search/RAG and DSPy are
          deterministic dev adapters until the real modules land.
        </p>

        <form className="explain-form" onSubmit={handleSubmit}>
          <label htmlFor="post-url">URL input</label>
          <input
            id="post-url"
            value={postUrl}
            onChange={(event) => setPostUrl(event.target.value)}
            placeholder="https://bsky.app/profile/{actor}/post/{rkey}"
          />

          <label htmlFor="provider">provider selector</label>
          <select id="provider" value={provider} onChange={(event) => setProvider(event.target.value)}>
            {(providers.length ? providers : [{ name: "openai", configured: false }]).map((item) => (
              <option key={item.name} value={item.name}>
                {item.name}
                {item.configured ? "" : " (not configured)"}
              </option>
            ))}
          </select>

          <button type="submit" disabled={requestState === "loading"}>
            {requestState === "loading" ? "Explaining..." : "Explain"}
          </button>
        </form>

        {error ? <div className="error-banner">{error}</div> : null}

        {result ? (
          <section className="result-view" aria-label="explanation result">
            <div className="post-summary">
              <strong>{result.post.author}</strong>
              <span>{new Date(result.post.created_at).toLocaleString()}</span>
            </div>

            <ol className="bullets">
              {result.bullets.map((bullet) => (
                <li key={bullet.text}>
                  <span>{bullet.text}</span>
                  <span className="citation-row" aria-label="citations">
                    {bullet.source_ids.map((sourceId) => (
                      <a key={sourceId} href={`#source-${sourceId}`} className="citation-chip">
                        {sourceId}
                      </a>
                    ))}
                  </span>
                </li>
              ))}
            </ol>

            <section className="source-list" aria-label="sources">
              <h2>Sources</h2>
              {result.sources.map((source) => (
                <article id={`source-${source.id}`} key={source.id}>
                  <strong>{source.id}</strong>
                  <a href={source.url} target="_blank" rel="noreferrer">
                    {source.title}
                  </a>
                  <small>{source.type}</small>
                  <p>{source.snippet}</p>
                </article>
              ))}
            </section>

            <div className="trust-display">
              trust display: {Math.round(result.trace.trust_score * 100)}% · fallback{" "}
              {result.trace.fallback_mode} · adapter {result.trace.adapter_mode}
            </div>

            <button type="button" className="trace-toggle" onClick={() => setShowTrace((value) => !value)}>
              trace panel
            </button>
            {showTrace ? (
              <pre className="trace-panel">{JSON.stringify(result.trace, null, 2)}</pre>
            ) : null}
          </section>
        ) : null}
      </section>
    </main>
  );
}
