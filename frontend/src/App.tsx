import { FormEvent, useEffect, useState } from "react";

import { type ExplainResponse, type ProviderInfo, explainPost, fetchProviders } from "./api/client";
import ErrorBanner from "./components/ErrorBanner";
import ResultView from "./components/ResultView";
import UrlForm from "./components/UrlForm";

const DEFAULT_PROVIDER: ProviderInfo = {
  name: "openai",
  configured: false,
  skipped_reason: null,
  default_model: null,
};

type RequestState = "idle" | "loading" | "success" | "error";

export default function App() {
  const [postUrl, setPostUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState(DEFAULT_PROVIDER.name);
  const [providers, setProviders] = useState<ProviderInfo[]>([DEFAULT_PROVIDER]);
  const [result, setResult] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [providerWarning, setProviderWarning] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");

  useEffect(() => {
    let ignore = false;

    fetchProviders()
      .then((items) => {
        if (ignore) {
          return;
        }
        const nextProviders = items.length ? items : [DEFAULT_PROVIDER];
        setProviders(nextProviders);
        setProvider((current) => (nextProviders.some((item) => item.name === current) ? current : nextProviders[0].name));
      })
      .catch(() => {
        if (!ignore) {
          setProviderWarning("Provider status is unavailable.");
          setProviders([DEFAULT_PROVIDER]);
        }
      });

    return () => {
      ignore = true;
    };
  }, []);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedUrl = postUrl.trim();
    const trimmedApiKey = apiKey.trim();
    setPostUrl(trimmedUrl);
    setApiKey(trimmedApiKey);
    setRequestState("loading");
    setError(null);
    setProviderWarning(null);
    setResult(null);

    if (!trimmedApiKey) {
      setError("OpenAI API key is required for embeddings and model-backed explanations.");
      setRequestState("error");
      return;
    }

    try {
      const response = await explainPost({
        post_url: trimmedUrl,
        provider,
        include_trace: true,
        api_key: trimmedApiKey,
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
        <header className="app-header">
          <p className="eyebrow">RapidCanvas</p>
          <h1 id="app-title">Bluesky Contextual Post Explainer</h1>
        </header>

        <UrlForm
          apiKey={apiKey}
          isLoading={requestState === "loading"}
          onApiKeyChange={setApiKey}
          onPostUrlChange={setPostUrl}
          onProviderChange={setProvider}
          onSubmit={handleSubmit}
          postUrl={postUrl}
          provider={provider}
          providers={providers}
        />

        {providerWarning ? <ErrorBanner tone="warning" message={providerWarning} /> : null}
        {error ? <ErrorBanner message={error} /> : null}

        <section className="result-region" aria-live="polite" aria-busy={requestState === "loading"}>
          {requestState === "loading" ? <div className="loading-state">Fetching context...</div> : null}
          {result ? <ResultView result={result} /> : null}
        </section>
      </section>
    </main>
  );
}
