import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import App from "./App";
import { type ExplainResponse } from "./api/client";

const baseResponse: ExplainResponse = {
  post: {
    url: "https://bsky.app/profile/example.com/post/3abcxyz",
    author: "example.com",
    text: "Fetched post",
    created_at: "2026-04-29T12:00:00Z",
  },
  bullets: [
    { text: "Fetched post text is available.", source_ids: ["S1"] },
    { text: "Trace marks deterministic adapters.", source_ids: ["S1", "S2"] },
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
    {
      id: "S2",
      title: "Bluesky parent context",
      url: "https://bsky.app/profile/example.com/post/3abcxyz",
      type: "bluesky",
      snippet: "Parent reply",
    },
  ],
  trace: {
    category: "gate3_vertical_slice",
    queries: ["example context"],
    warnings: ["real_bluesky_fetch_enabled"],
    latency_ms: 12,
    trust_score: 0.35,
    fallback_mode: "safe_summary",
    guardrail_flags: ["dev_adapter_search_rag", "dev_adapter_dspy"],
    adapter_mode: "deterministic_dev",
    adapter_notes: ["Adapters are non-final."],
  },
};

const providersPayload = {
  providers: [
    {
      name: "openai",
      configured: false,
      skipped_reason: "OPENAI_API_KEY is not configured",
      default_model: "openai/gpt-4.1-mini",
    },
    {
      name: "ollama",
      configured: true,
      skipped_reason: null,
      default_model: "llama3.2",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockFetch(response: ExplainResponse = baseResponse) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url.endsWith("/api/explain")) {
      return Promise.resolve(jsonResponse(response));
    }
    return Promise.reject(new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`));
  });
}

function htmlResponse(): Response {
  return new Response("<!doctype html><title>Preview</title>", {
    status: 200,
    headers: { "Content-Type": "text/html" },
  });
}

async function fillRequiredFields(apiKey = "sk-ui-test-key") {
  const urlInput = await screen.findByLabelText("Bluesky post URL");
  const keyInput = await screen.findByLabelText("OpenAI API key");
  fireEvent.change(urlInput, {
    target: { value: " https://bsky.app/profile/example.com/post/3abcxyz " },
  });
  fireEvent.change(keyInput, { target: { value: ` ${apiKey} ` } });
}

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  cleanup();
});

test("renders the application shell and provider selector", async () => {
  mockFetch();
  render(<App />);

  expect(screen.getByRole("heading", { name: "Bluesky Contextual Post Explainer" })).toBeVisible();
  expect(await screen.findByLabelText("Bluesky post URL")).toHaveValue("");
  expect(await screen.findByLabelText("OpenAI API key")).toHaveAttribute("type", "password");
  expect(screen.getByText("Required for embeddings and model calls. Not saved.")).toBeVisible();
  expect(await screen.findByRole("combobox", { name: "Provider" })).toHaveTextContent("openai");
  expect(screen.getByText("skipped - OPENAI_API_KEY is not configured - openai/gpt-4.1-mini")).toBeVisible();
});

test("submits a Bluesky URL through the typed API client", async () => {
  const fetchMock = mockFetch();
  render(<App />);

  await fillRequiredFields();
  expect(screen.getByText("ready with request key - openai/gpt-4.1-mini")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
  const explainCall = fetchMock.mock.calls.find(([inputArg]) => String(inputArg).endsWith("/api/explain"));
  expect(explainCall?.[1]?.method).toBe("POST");
  expect(JSON.parse(String(explainCall?.[1]?.body))).toMatchObject({
    post_url: "https://bsky.app/profile/example.com/post/3abcxyz",
    provider: "openai",
    include_trace: true,
    api_key: "sk-ui-test-key",
  });
});

test("shows honest request status while the explanation is running", async () => {
  const pendingExplain: Array<() => void> = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url.endsWith("/api/explain")) {
      return new Promise<Response>((resolve) => {
        pendingExplain.push(() => resolve(jsonResponse(baseResponse)));
      });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Request sent to the FastAPI explainer.")).toBeVisible();
  expect(screen.getByText(/Provider: openai/)).toBeVisible();
  expect(screen.getByText(/exact fetch, search, retrieval, and citation details will appear in the trace/)).toBeVisible();
  expect(screen.getByText("...")).toBeVisible();
  expect(screen.queryByText("Searching for relevant context")).not.toBeInTheDocument();
  expect(screen.queryByText("Ranking evidence and checking citations")).not.toBeInTheDocument();

  expect(pendingExplain).toHaveLength(1);
  pendingExplain[0]();
  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
});

test("prevents native form navigation and handles submission in React", async () => {
  mockFetch();
  const { container } = render(<App />);

  await fillRequiredFields();
  const form = container.querySelector("form");
  expect(form).not.toBeNull();
  expect(form).toHaveAttribute("novalidate");

  const submitEvent = new Event("submit", { bubbles: true, cancelable: true });
  form?.dispatchEvent(submitEvent);

  expect(submitEvent.defaultPrevented).toBe(true);
  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
});

test("keeps optional provider skip reasons visible when only OpenAI request key is present", async () => {
  mockFetch();
  render(<App />);

  await fillRequiredFields();
  const providerSelect = await screen.findByRole("combobox", { name: "Provider" });
  fireEvent.change(providerSelect, { target: { value: "ollama" } });

  expect(screen.getByText("ready - llama3.2")).toBeVisible();
});

test("falls back to the local backend when same-origin preview is not the API", async () => {
  const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url === "/api/providers") {
      return Promise.resolve(htmlResponse());
    }
    if (url === "http://127.0.0.1:8000/api/providers") {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url === "/api/explain") {
      return Promise.resolve(jsonResponse({ detail: "not found" }, 404));
    }
    if (url === "http://127.0.0.1:8000/api/explain") {
      return Promise.resolve(jsonResponse(baseResponse));
    }
    return Promise.reject(new Error(`Unexpected request: ${url} ${init?.method ?? "GET"}`));
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith("http://127.0.0.1:8000/api/providers", undefined);
  expect(fetchMock.mock.calls.some(([input]) => String(input) === "http://127.0.0.1:8000/api/explain")).toBe(true);
});

test("submits the selected provider", async () => {
  const fetchMock = mockFetch();
  render(<App />);

  await fillRequiredFields();
  const providerSelect = await screen.findByRole("combobox", { name: "Provider" });
  fireEvent.change(providerSelect, { target: { value: "ollama" } });
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Fetched post text is available.")).toBeVisible();
  const explainCall = fetchMock.mock.calls.find(([inputArg]) => String(inputArg).endsWith("/api/explain"));
  expect(JSON.parse(String(explainCall?.[1]?.body))).toMatchObject({
    provider: "ollama",
  });
});

test("renders cited bullets and source cards", async () => {
  mockFetch();
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  const bullets = await screen.findByLabelText("explanation bullets");
  expect(within(bullets).getAllByRole("listitem")).toHaveLength(3);
  expect(screen.getAllByLabelText("Citation S1: Bluesky post by example.com")).toHaveLength(3);
  expect(screen.getByLabelText("Citation S2: Bluesky parent context")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Sources" })).toBeVisible();
  expect(screen.getByText("Parent reply")).toBeVisible();
});

test("toggles trace details with trust, fallback, warnings, and guardrail flags", async () => {
  mockFetch();
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByLabelText("trust and fallback status")).toHaveTextContent("Safe summary");
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("dev adapter dspy");

  fireEvent.click(screen.getByRole("button", { name: "Show trace" }));

  await waitFor(() => {
    expect(screen.getByText("gate3_vertical_slice")).toBeVisible();
    expect(screen.getAllByText("real_bluesky_fetch_enabled")[0]).toBeVisible();
    expect(screen.getByText("deterministic dev")).toBeVisible();
  });
});

test("summarizes common retrieval diagnostics without making successful load notes look like errors", async () => {
  mockFetch({
    ...baseResponse,
    trace: {
      ...baseResponse.trace,
      warnings: [
        "video_embed_unparsed: the post contains video, and this build uses the post text/thread/link/image evidence without parsing video frames.",
        "qdrant_unavailable_using_in_memory_vector_store:RuntimeError",
        "bluesky_search_failed:BlueskyClientError",
        "content_truncated",
        "http_status:403",
        "empty_extracted_text",
        "optimized_dspy_program_loaded",
        "optimized_program_loaded",
      ],
    },
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByText("Retrieval notes")).toBeVisible();
  expect(screen.getByLabelText("warnings")).toHaveTextContent("This post contains a video");
  expect(screen.getByLabelText("warnings")).toHaveTextContent("Vector database was unavailable");
  expect(screen.getByLabelText("warnings")).toHaveTextContent("Bluesky search was unavailable");
  expect(screen.getByLabelText("warnings")).not.toHaveTextContent("optimized_dspy_program_loaded");
  fireEvent.click(screen.getByRole("button", { name: "Show trace" }));
  expect(screen.getByText("optimized_dspy_program_loaded")).toBeVisible();
});

test("renders a partial-success state distinctly", async () => {
  mockFetch({
    ...baseResponse,
    trace: {
      ...baseResponse.trace,
      trust_score: 0.52,
      fallback_mode: "partial",
      guardrail_flags: ["low_evidence"],
    },
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByLabelText("trust and fallback status")).toHaveTextContent("Partial");
  expect(screen.getByText("Only supported points are shown.")).toBeVisible();
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("low evidence");
});

test("renders an abstain state distinctly", async () => {
  mockFetch({
    ...baseResponse,
    trace: {
      ...baseResponse.trace,
      trust_score: 0.08,
      fallback_mode: "abstain",
      guardrail_flags: ["low_evidence"],
    },
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByLabelText("trust and fallback status")).toHaveTextContent("Abstain");
  expect(screen.getByText("Evidence was not sufficient for a contextual explanation.")).toBeVisible();
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("low evidence");
});

test("renders API errors", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    return Promise.resolve(jsonResponse({ detail: { message: "Bluesky fetch failed" } }, 502));
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Bluesky fetch failed");
});
