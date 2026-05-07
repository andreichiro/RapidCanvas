import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import App from "../App";
import { type ExplainResponse } from "../api/client";
import ResultView from "../components/ResultView";
import {
  gate6AbstainResponse,
  gate6ContradictoryResponse,
  gate6LowTrustResponse,
  gate6NormalResponse,
  gate6PartialResponse,
  gate6PromptInjectionResponse,
  gate6SafeSummaryResponse,
  gate6ResponseWithTrace,
} from "./fixtures/gate6QualityResponses";

const providersPayload = {
  providers: [
    {
      name: "openai",
      configured: true,
      skipped_reason: null,
      runnable: true,
      default_model: "openai/gpt-4.1-mini",
      comparison_status: "configured_not_run",
    },
  ],
};

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mockAppFetch(payload: ExplainResponse | { detail: unknown }, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
    const url = String(input);
    if (url.endsWith("/api/providers")) {
      return Promise.resolve(jsonResponse(providersPayload));
    }
    if (url.endsWith("/api/explain")) {
      return Promise.resolve(jsonResponse(payload, status));
    }
    return Promise.reject(new Error(`Unexpected request: ${url}`));
  });
}

async function fillAppForm() {
  fireEvent.change(await screen.findByLabelText("Bluesky post URL"), {
    target: { value: "https://bsky.app/profile/example.com/post/3abcxyz" },
  });
  fireEvent.change(await screen.findByLabelText("OpenAI API key"), {
    target: { value: "sk-ui-test-key" },
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders a normal Gate 6 quality response with 3-5 cited bullets and sources", () => {
  render(<ResultView result={gate6NormalResponse} />);

  const bullets = screen.getByLabelText("explanation bullets");
  expect(within(bullets).getAllByRole("listitem")).toHaveLength(4);
  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent("Normal");
  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent("86%");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  for (const source of gate6NormalResponse.sources) {
    const citations = screen.getAllByLabelText(`Citation ${source.id}: ${source.title}`);
    expect(citations.length).toBeGreaterThan(0);
    for (const citation of citations) {
      expect(citation).toHaveAttribute("href", `#source-${source.id}`);
    }
    expect(document.querySelector(`#source-${source.id}`)).not.toBeNull();
  }

  const sources = screen.getByLabelText("sources");
  for (const sourceId of ["S-post", "S-thread", "S-web", "S-image"]) {
    expect(within(sources).getByText(sourceId)).toBeVisible();
  }
  for (const typeLabel of ["Thread", "Bluesky", "Web", "Image"]) {
    expect(within(sources).getByText(typeLabel)).toBeVisible();
  }
  expect(within(sources).getByLabelText("source quality S-web")).toHaveTextContent("Quality 91%");
  expect(within(sources).getByLabelText("source quality S-web")).toHaveTextContent("Citation eligible");
  expect(within(sources).getByText("authoritative linked coverage")).toBeVisible();
  expect(within(sources).getByText("current source")).toBeVisible();
  expect(screen.getByLabelText("runtime summary")).toHaveTextContent("Vector backend");
  expect(screen.getByLabelText("runtime summary")).toHaveTextContent("qdrant vector store");
  expect(screen.getByLabelText("image and video evidence")).toHaveTextContent("Image 1");
  expect(screen.getByLabelText("image and video evidence")).toHaveTextContent("vision yes");
});

test("links citations to source cards even when backend source ids need fragment encoding", () => {
  const specialSourceId = "S weird/#1";
  const response: ExplainResponse = {
    ...gate6NormalResponse,
    bullets: [
      {
        text: "Special source ids remain linkable without changing the backend id shown to users.",
        source_ids: [specialSourceId],
      },
      ...gate6NormalResponse.bullets.slice(0, 2),
    ],
    sources: [
      {
        id: specialSourceId,
        title: "Special source id fixture",
        url: "https://example.com/special-source-id",
        type: "web",
        snippet: "A source id with spaces, slash, and hash-like characters.",
      },
      ...gate6NormalResponse.sources,
    ],
  };
  render(<ResultView result={response} />);

  const citation = screen.getByLabelText(`Citation ${specialSourceId}: Special source id fixture`);
  expect(citation).toHaveTextContent(specialSourceId);
  expect(citation).toHaveAttribute("href", "#source-S%20weird%2F%231");
  expect(document.getElementById("source-S%20weird%2F%231")).not.toBeNull();
});

test.each([
  ["partial", gate6PartialResponse, "Partial", "Only supported points are shown.", "low evidence warning"],
  ["abstain", gate6AbstainResponse, "Abstain", "Evidence was not sufficient for a contextual explanation.", "unavailable_or_deleted"],
  ["safe_summary", gate6SafeSummaryResponse, "Safe summary", "The answer is limited to visible post and thread context.", "provider_upstream_error"],
] as const)("renders the %s fallback state from backend trace fields", (mode, response, badge, banner, warning) => {
  const { container } = render(<ResultView result={response} />);

  expect(container.querySelector(".result-view")).toHaveClass(`fallback-${mode}`);
  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent(badge);
  expect(screen.getByRole("status")).toHaveTextContent(banner);
  expect(screen.getByLabelText("warnings")).toHaveTextContent(warning);
});

test("renders prompt-injection, contradictory-source, and low-trust warning states", () => {
  const { rerender } = render(<ResultView result={gate6PromptInjectionResponse} />);
  expect(screen.getByLabelText("warnings")).toHaveTextContent("prompt_injection_risk");
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("prompt injection risk");
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("disable citations");

  rerender(<ResultView result={gate6ContradictoryResponse} />);
  expect(screen.getByLabelText("warnings")).toHaveTextContent("contradictory_sources");
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("conflicting sources");

  rerender(<ResultView result={gate6LowTrustResponse} />);
  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent("18%");
  expect(screen.getByLabelText("warnings")).toHaveTextContent("low_trust");
  expect(screen.getByLabelText("guardrail flags")).toHaveTextContent("weak retrieval score");
});

test("renders explicit video-unparsed evidence status without implying frame analysis", () => {
  render(
    <ResultView
      result={gate6ResponseWithTrace({
        image_status: [],
        warnings: [
          "video_embed_unparsed: the post contains video, and this build uses text/thread/link/image evidence without parsing video frames.",
        ],
      })}
    />,
  );

  expect(screen.getByLabelText("image and video evidence")).toHaveTextContent("Video evidence");
  expect(screen.getByLabelText("image and video evidence")).toHaveTextContent("video frames are not parsed");
  expect(screen.getByLabelText("warnings")).toHaveTextContent("This post contains a video");
});

test("trace panel exposes backend quality fields without frontend scoring", () => {
  render(
    <ResultView
      result={gate6ResponseWithTrace({
        category: "contradiction_check",
        queries: [
          "very long contradiction query with source ids and quoted terms that should remain readable in the trace panel",
        ],
        warnings: ["contradictory_sources: backend kept the answer partial"],
        latency_ms: 987,
        trust_score: 0.37,
        fallback_mode: "partial",
        guardrail_flags: ["conflicting_sources"],
        adapter_mode: "deterministic_fallback",
        adapter_notes: ["fixture-only adapter note mirrors a backend trace field"],
      })}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Show trace" }));

  const tracePanel = screen.getByLabelText("trace panel");
  for (const label of [
    "Category",
    "Request ID",
    "Provider",
    "Vector backend",
    "Latency",
    "Trust score",
    "Fallback mode",
    "Adapter mode",
    "Queries",
    "Warnings",
    "Guardrail flags",
    "Adapter notes",
    "Source quality",
    "Image status",
    "Live quality notes",
  ]) {
    expect(within(tracePanel).getByText(label)).toBeVisible();
  }
  expect(within(tracePanel).getByText("contradiction_check")).toBeVisible();
  expect(within(tracePanel).getByText("req-gate6-quality-smoke")).toBeVisible();
  expect(within(tracePanel).getByText("openai")).toBeVisible();
  expect(within(tracePanel).getByText("qdrant vector store")).toBeVisible();
  expect(within(tracePanel).getByText("987 ms")).toBeVisible();
  expect(within(tracePanel).getByText("37%")).toBeVisible();
  expect(within(tracePanel).getByText("partial")).toBeVisible();
  expect(within(tracePanel).getByText("deterministic fallback")).toBeVisible();
  expect(within(tracePanel).getByText("conflicting_sources")).toBeVisible();
  expect(within(tracePanel).getByText("very long contradiction query with source ids and quoted terms that should remain readable in the trace panel")).toBeVisible();
  expect(screen.getAllByText("contradictory_sources: backend kept the answer partial")).toHaveLength(2);
  expect(within(tracePanel).getByText("fixture-only adapter note mirrors a backend trace field")).toBeVisible();
});

test("renders unavailable or deleted post errors clearly", async () => {
  mockAppFetch({ detail: "Post is unavailable or deleted." }, 404);
  render(<App />);

  await fillAppForm();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Post is unavailable or deleted.");
});

test("renders provider or upstream errors clearly", async () => {
  mockAppFetch(
    {
      detail: {
        code: "provider_upstream_error",
        message: "Provider upstream failed; try again later.",
      },
    },
    502,
  );
  render(<App />);

  await fillAppForm();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("Provider upstream failed; try again later.");
  expect(screen.getByRole("alert")).toHaveTextContent("provider_upstream_error");
  expect(screen.getByRole("alert")).toHaveTextContent("HTTP 502");
});

test("renders FastAPI validation detail arrays clearly", async () => {
  mockAppFetch(
    {
      detail: [
        {
          msg: "post_url must match https://bsky.app/profile/{actor}/post/{rkey}",
        },
      ],
    },
    422,
  );
  render(<App />);

  await fillAppForm();
  fireEvent.click(await screen.findByRole("button", { name: "Explain" }));

  expect(await screen.findByRole("alert")).toHaveTextContent(
    "post_url must match https://bsky.app/profile/{actor}/post/{rkey}",
  );
});
