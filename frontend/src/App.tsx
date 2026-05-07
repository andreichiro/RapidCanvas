import { FormEvent, useEffect, useRef, useState } from "react";

import { ApiRequestError, type ExplainResponse, type ProviderInfo, explainPost, fetchProviders } from "./api/client";
import ErrorBanner from "./components/ErrorBanner";
import ResultView from "./components/ResultView";
import UrlForm from "./components/UrlForm";

const DEFAULT_PROVIDER: ProviderInfo = {
  name: "openai",
  configured: false,
  skipped_reason: null,
  runnable: false,
  default_model: null,
  comparison_status: null,
};

type RequestState = "idle" | "loading" | "success" | "error";

type DisplayError = {
  code?: string;
  details?: string[];
  message: string;
  status?: number;
  title: string;
};

function displayErrorFrom(caught: unknown): DisplayError {
  if (caught instanceof ApiRequestError) {
    return {
      code: caught.code,
      details: caught.details,
      message: caught.message,
      status: caught.status,
      title: "API request failed",
    };
  }

  return {
    message: caught instanceof Error ? caught.message : "Unable to explain this post.",
    title: "Request failed",
  };
}

export default function App() {
  const [postUrl, setPostUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [provider, setProvider] = useState(DEFAULT_PROVIDER.name);
  const [providers, setProviders] = useState<ProviderInfo[]>([DEFAULT_PROVIDER]);
  const [result, setResult] = useState<ExplainResponse | null>(null);
  const [error, setError] = useState<DisplayError | null>(null);
  const [providerWarning, setProviderWarning] = useState<string | null>(null);
  const [requestState, setRequestState] = useState<RequestState>("idle");
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const explainAbortRef = useRef<AbortController | null>(null);

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

  useEffect(() => () => explainAbortRef.current?.abort(), []);

  useEffect(() => {
    if (requestState !== "loading") {
      return;
    }
    setElapsedSeconds(0);
    const timer = window.setInterval(() => {
      setElapsedSeconds((current) => current + 1);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [requestState]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedUrl = postUrl.trim();
    const trimmedApiKey = apiKey.trim();
    setPostUrl(trimmedUrl);
    setApiKey(trimmedApiKey);
    setElapsedSeconds(0);
    setRequestState("loading");
    setError(null);
    setProviderWarning(null);
    setResult(null);

    if (!trimmedApiKey) {
      setError({
        code: "missing_request_api_key",
        message: "OpenAI API key is required for embeddings and model-backed explanations.",
        title: "API key required",
      });
      setRequestState("error");
      return;
    }

    const controller = new AbortController();
    explainAbortRef.current = controller;

    try {
      const response = await explainPost({
        post_url: trimmedUrl,
        provider,
        include_trace: true,
        api_key: trimmedApiKey,
      }, controller.signal);
      setResult(response);
      setRequestState("success");
    } catch (caught) {
      if (controller.signal.aborted) {
        setError({
          code: "request_canceled",
          message: "Request canceled.",
          title: "Request canceled",
        });
        setRequestState("idle");
      } else {
        setError(displayErrorFrom(caught));
        setRequestState("error");
      }
    } finally {
      if (explainAbortRef.current === controller) {
        explainAbortRef.current = null;
      }
    }
  }

  function handleCancel() {
    explainAbortRef.current?.abort();
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
          onCancel={handleCancel}
          postUrl={postUrl}
          provider={provider}
          providers={providers}
        />

        {providerWarning ? <ErrorBanner tone="warning" message={providerWarning} /> : null}
        {error ? (
          <ErrorBanner
            code={error.code}
            details={error.details}
            message={error.message}
            status={error.status}
            title={error.title}
          />
        ) : null}

        <section className="result-region" aria-live="polite" aria-busy={requestState === "loading"}>
          {requestState === "loading" ? (
            <div className="loading-state">
              <span className="loading-icon" aria-hidden="true">
                ...
              </span>
              <span className="loading-copy">
                <span className="loading-title">Request sent to the FastAPI explainer.</span>
                <span className="loading-detail">
                  Provider: {provider}. Waiting {elapsedSeconds}s for the backend response; exact fetch, search,
                  retrieval, and citation details will appear in the trace when it returns.
                </span>
              </span>
            </div>
          ) : null}
          {result ? <ResultView result={result} /> : null}
        </section>
      </section>
    </main>
  );
}
