import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "../App";
import { explainPost, fetchProviders } from "../api/client";
import { gate6NormalResponse } from "./fixtures/gate6QualityResponses";

const providersPayload = {
  providers: [
    {
      name: "openai",
      configured: false,
      skipped_reason: "OPENAI_API_KEY is not configured",
      runnable: false,
      default_model: "openai/gpt-4.1-mini",
      comparison_status: "skipped",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
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

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

test("cancels an in-flight explanation request", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url.endsWith("/api/explain")) {
      return new Promise<Response>((_resolve, reject) => {
        if (init?.signal?.aborted) {
          reject(new DOMException("The operation was aborted.", "AbortError"));
          return;
        }
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("The operation was aborted.", "AbortError"));
        });
      });
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("button", { name: "Cancel" })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Request canceled.");
  expect(screen.queryByText("Request sent to the FastAPI explainer.")).not.toBeInTheDocument();
});

test("does not render malformed successful JSON as an explanation", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url.endsWith("/api/explain")) {
      return Promise.resolve(jsonResponse({ ok: true }));
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
  render(<App />);

  await fillRequiredFields();
  fireEvent.click(screen.getByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "API response did not match the explanation contract.",
  );
  expect(screen.queryByRole("heading", { name: "English explanation" })).not.toBeInTheDocument();
});

test("rejects malformed optional source quality fields before rendering", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/explain")) {
      return Promise.resolve(
        jsonResponse({
          ...gate6NormalResponse,
          sources: [
            {
              ...gate6NormalResponse.sources[0],
              quality_reasons: "not-an-array",
            },
            ...gate6NormalResponse.sources.slice(1),
          ],
        }),
      );
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });

  await expect(
    explainPost({
      include_trace: true,
      post_url: "https://bsky.app/profile/example.com/post/3abcxyz",
      provider: "openai",
    }),
  ).rejects.toThrow("API response did not match the explanation contract.");
});

test("normalizes legacy deterministic adapter mode without showing the old label", async () => {
  vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/explain")) {
      return Promise.resolve(
        jsonResponse({
          ...gate6NormalResponse,
          trace: {
            ...gate6NormalResponse.trace,
            adapter_mode: "deterministic_dev",
          },
        }),
      );
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });

  const response = await explainPost({
    include_trace: true,
    post_url: "https://bsky.app/profile/example.com/post/3abcxyz",
    provider: "openai",
  });

  expect(response.trace.adapter_mode).toBe("deterministic_fallback");
});

test("rejects malformed provider status payloads", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(
    jsonResponse({
      providers: [
        {
          name: "openai",
          configured: true,
          skipped_reason: null,
          runnable: "yes",
        },
      ],
    }),
  );

  await expect(fetchProviders()).rejects.toThrow("API provider response did not match the provider contract.");
});
