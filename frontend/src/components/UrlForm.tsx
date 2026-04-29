import { type FormEvent } from "react";

import { type ProviderInfo } from "../api/client";
import ProviderSelect from "./ProviderSelect";

type UrlFormProps = {
  isLoading: boolean;
  onPostUrlChange: (value: string) => void;
  onProviderChange: (provider: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  postUrl: string;
  provider: string;
  providers: ProviderInfo[];
};

export default function UrlForm({
  isLoading,
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
      <div className="url-field">
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
      </div>

      <div className="provider-field">
        <label htmlFor="provider">Provider</label>
        <ProviderSelect disabled={isLoading} onChange={onProviderChange} provider={provider} providers={providers} />
        <span className="provider-status" id="provider-status">
          {selectedProvider?.skipped_reason ?? selectedProvider?.default_model ?? "default"}
        </span>
      </div>

      <button className="submit-button" disabled={isLoading} type="submit">
        {isLoading ? "Explaining..." : "Explain"}
      </button>
    </form>
  );
}
