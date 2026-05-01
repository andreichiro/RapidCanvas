import { type FormEvent } from "react";

import { type ProviderInfo } from "../api/client";
import ProviderSelect from "./ProviderSelect";

type UrlFormProps = {
  apiKey: string;
  isLoading: boolean;
  onApiKeyChange: (value: string) => void;
  onPostUrlChange: (value: string) => void;
  onProviderChange: (provider: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  postUrl: string;
  provider: string;
  providers: ProviderInfo[];
};

function providerStatusText(provider?: ProviderInfo): string {
  if (!provider) {
    return "default";
  }

  const details = [provider.configured ? "ready" : "skipped"];

  if (provider.skipped_reason) {
    details.push(provider.skipped_reason);
  }
  if (provider.default_model) {
    details.push(provider.default_model);
  }

  return details.join(" - ");
}

export default function UrlForm({
  apiKey,
  isLoading,
  onApiKeyChange,
  onPostUrlChange,
  onProviderChange,
  onSubmit,
  postUrl,
  provider,
  providers,
}: UrlFormProps) {
  const selectedProvider = providers.find((item) => item.name === provider);

  return (
    <form className="explain-form" onSubmit={onSubmit}>
      <div className="url-field form-field">
        <label htmlFor="post-url">Bluesky post URL</label>
        <input
          autoComplete="off"
          disabled={isLoading}
          id="post-url"
          onChange={(event) => onPostUrlChange(event.target.value)}
          placeholder="https://bsky.app/profile/{actor}/post/{rkey}"
          required
          type="url"
          value={postUrl}
        />
        <span className="field-helper" aria-hidden="true">
          &nbsp;
        </span>
      </div>

      <div className="api-key-field form-field">
        <label htmlFor="api-key">OpenAI API key</label>
        <input
          autoComplete="off"
          disabled={isLoading}
          id="api-key"
          onChange={(event) => onApiKeyChange(event.target.value)}
          placeholder="sk-..."
          required
          spellCheck={false}
          type="password"
          value={apiKey}
        />
        <span className="field-helper">Required for embeddings and model calls. Not saved.</span>
      </div>

      <div className="provider-field form-field">
        <label htmlFor="provider">Provider</label>
        <ProviderSelect disabled={isLoading} onChange={onProviderChange} provider={provider} providers={providers} />
        <span className="provider-status" id="provider-status">
          {providerStatusText(selectedProvider)}
        </span>
      </div>

      <div className="submit-field">
        <span className="submit-label-spacer" aria-hidden="true">
          &nbsp;
        </span>
        <button className="submit-button" disabled={isLoading} type="submit">
          {isLoading ? "Explaining..." : "Explain"}
        </button>
        <span className="submit-helper" aria-hidden="true">
          &nbsp;
        </span>
      </div>
    </form>
  );
}
