import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { type ProviderInfo } from "../api/client";
import ProviderSelect from "../components/ProviderSelect";
import UrlForm from "../components/UrlForm";

const providers: ProviderInfo[] = [
  {
    name: "openai",
    configured: false,
    skipped_reason: "OPENAI_API_KEY is not configured",
    runnable: false,
    default_model: "openai/gpt-4.1-mini",
    comparison_status: "skipped",
  },
  {
    name: "gemini",
    configured: true,
    skipped_reason: null,
    runnable: true,
    default_model: "gemini-2.5-flash",
    comparison_status: "ran",
  },
  {
    name: "ollama",
    configured: true,
    skipped_reason: null,
    runnable: false,
    default_model: "llama3.2",
    comparison_status: "configured_not_run",
  },
];

afterEach(() => {
  cleanup();
});

test("provider options expose runnable, skipped, default model, and comparison labels", () => {
  render(<ProviderSelect onChange={vi.fn()} provider="openai" providers={providers} />);

  expect(screen.getByRole("option", { name: "openai (skipped, default openai/gpt-4.1-mini, comparison skipped)" })).toBeVisible();
  expect(screen.getByRole("option", { name: "gemini (runnable, default gemini-2.5-flash, comparison ran)" })).toBeVisible();
  expect(screen.getByRole("option", { name: "ollama (configured, default llama3.2, configured, not run)" })).toBeVisible();
});

test("provider status helper distinguishes request-key readiness from configured providers", () => {
  const noop = vi.fn();

  const { rerender } = render(
    <UrlForm
      apiKey=""
      isLoading={false}
      onApiKeyChange={noop}
      onCancel={noop}
      onPostUrlChange={noop}
      onProviderChange={noop}
      onSubmit={noop}
      postUrl=""
      provider="openai"
      providers={providers}
    />,
  );

  expect(screen.getByText("Skipped - OPENAI_API_KEY is not configured - default model openai/gpt-4.1-mini - comparison skipped")).toBeVisible();

  rerender(
    <UrlForm
      apiKey="sk-test"
      isLoading={false}
      onApiKeyChange={noop}
      onCancel={noop}
      onPostUrlChange={noop}
      onProviderChange={noop}
      onSubmit={noop}
      postUrl=""
      provider="openai"
      providers={providers}
    />,
  );

  expect(screen.getByText("Runnable with request key - default model openai/gpt-4.1-mini - comparison skipped")).toBeVisible();

  rerender(
    <UrlForm
      apiKey=""
      isLoading={false}
      onApiKeyChange={noop}
      onCancel={noop}
      onPostUrlChange={noop}
      onProviderChange={noop}
      onSubmit={noop}
      postUrl=""
      provider="gemini"
      providers={providers}
    />,
  );

  expect(screen.getByText("Runnable - default model gemini-2.5-flash - comparison ran")).toBeVisible();
});
