import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "./App";

const explainResponse = {
  post: {
    url: "https://bsky.app/profile/example.com/post/3abcxyz",
    author: "example.com",
    text: "Fetched post",
    created_at: "2026-04-29T12:00:00Z",
  },
  bullets: [
    { text: "Fetched post text is available.", source_ids: ["S1"] },
    { text: "Trace marks deterministic adapters.", source_ids: ["S1"] },
    { text: "This is not final Search/RAG or DSPy behavior.", source_ids: ["S1"] },
  ],
  sources: [
    {
      id: "S1",
      title: "Bluesky post by example.com",
      url: "https://bsky.app/profile/example.com/post/3abcxyz",
      type: "thread",
      snippet: "Fetched post",
    },
  ],
  trace: {
    category: "gate3_vertical_slice",
    queries: [],
    warnings: ["real_bluesky_fetch_enabled"],
    latency_ms: 12,
    trust_score: 0.35,
    fallback_mode: "safe_summary",
    guardrail_flags: ["dev_adapter_search_rag", "dev_adapter_dspy"],
    adapter_mode: "deterministic_dev",
    adapter_notes: ["Adapters are non-final."],
  },
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(
        new Response(
          JSON.stringify({
            providers: [
              {
                name: "openai",
                configured: false,
                skipped_reason: "OPENAI_API_KEY is not configured",
                default_model: null,
              },
            ],
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(explainResponse), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
});

afterEach(() => {
  cleanup();
});

test("renders the Gate 3 application shell", async () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Bluesky Contextual Post Explainer" })).toBeVisible();
  expect(screen.getByText(/T0 scaffold/)).toBeVisible();
  expect(await screen.findByLabelText("URL input")).toBeVisible();
});

test("submits a Bluesky URL and renders cited bullets, trust display, and trace panel", async () => {
  render(<App />);

  fireEvent.change(await screen.findByLabelText("URL input"), {
    target: { value: "https://bsky.app/profile/example.com/post/3abcxyz" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
  expect(screen.getAllByLabelText("citations")[0]).toHaveTextContent("S1");
  expect(screen.getByText(/trust display/i)).toHaveTextContent("safe_summary");

  fireEvent.click(screen.getByRole("button", { name: "trace panel" }));

  await waitFor(() => {
    expect(screen.getByText(/dev_adapter_dspy/)).toBeVisible();
  });
});
