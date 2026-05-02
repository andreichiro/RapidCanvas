import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import { explainPost } from "../api/client";
import ResultView from "../components/ResultView";
import { gate5ExplainResponse, gate5ResponseWithTrace } from "./fixtures/gate5ExplainResponse";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("renders the normal Gate 5 response with cited bullets and every source type", () => {
  render(<ResultView result={gate5ExplainResponse} />);

  expect(screen.getByRole("heading", { name: "English explanation" })).toBeVisible();
  expect(screen.getByText("Original post text (author's language)")).toBeVisible();
  const bullets = screen.getByLabelText("explanation bullets");
  expect(within(bullets).getAllByRole("listitem")).toHaveLength(4);
  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent("Normal");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();

  const [webCitation] = screen.getAllByLabelText("Citation web-result: External coverage of image carousel feedback");
  expect(webCitation).toHaveAttribute("href", "#source-web-result");
  expect(document.querySelector("#source-web-result")).not.toBeNull();

  const sources = screen.getByLabelText("sources");
  for (const typeLabel of ["Thread", "Bluesky", "Web", "Image"]) {
    expect(within(sources).getByText(typeLabel)).toBeVisible();
  }
  expect(within(sources).getByText("External coverage of image carousel feedback")).toBeVisible();
  expect(within(sources).getByText("https://example.com/bluesky-carousel-feedback")).toBeVisible();
  expect(within(sources).getByText("Coverage summarizes user feedback and planned changes.")).toBeVisible();
});

test("keeps long trace warnings and query lists scannable", () => {
  render(<ResultView result={gate5ExplainResponse} />);

  expect(screen.getByLabelText("warnings")).toHaveTextContent("retrieval warning");
  fireEvent.click(screen.getByRole("button", { name: "Show trace" }));

  expect(screen.getByText("Trust score")).toBeVisible();
  expect(screen.getByText("Fallback mode")).toBeVisible();
  expect(screen.getByText("Adapter mode")).toBeVisible();
  expect(screen.getByText("Guardrail flags")).toBeVisible();
  expect(screen.getByText("long retrieval query with multiple quoted terms and source filters that should wrap cleanly inside the trace panel")).toBeVisible();
  expect(screen.getAllByText("low evidence warning: fewer than three independent evidence chunks were available")[0]).toBeVisible();
});

test.each([
  ["partial", "Partial", "Only supported points are shown."],
  ["safe_summary", "Safe summary", "The answer is limited to visible post and thread context."],
  ["abstain", "Abstain", "Evidence was not sufficient for a contextual explanation."],
] as const)("renders the %s fallback state from backend trace fields", (fallbackMode, badgeLabel, bannerCopy) => {
  render(<ResultView result={gate5ResponseWithTrace({ fallback_mode: fallbackMode, trust_score: 0.32 })} />);

  expect(screen.getByLabelText("trust and fallback status")).toHaveTextContent(badgeLabel);
  expect(screen.getByRole("status")).toHaveTextContent(bannerCopy);
});

test("renders Gate 5 guardrail flags without hiding backend values", () => {
  render(
    <ResultView
      result={gate5ResponseWithTrace({
        guardrail_flags: [
          "prompt_injection_risk",
          "private_url_blocked",
          "source_safety_private_url_blocked",
          "dspy_provider_error",
          "unknown_citation",
          "uncited_output",
        ],
      })}
    />,
  );

  const flags = screen.getByLabelText("guardrail flags");
  expect(flags).toHaveTextContent("prompt injection risk");
  expect(flags).toHaveTextContent("private url blocked");
  expect(flags).toHaveTextContent("source safety private url blocked");
  expect(flags).toHaveTextContent("dspy provider error");
  expect(flags).toHaveTextContent("unknown citation");
  expect(flags).toHaveTextContent("uncited output");
});

test("does not warn when backend string arrays contain repeated display values", () => {
  const errorSpy = vi.spyOn(console, "error").mockImplementation(() => undefined);

  render(
    <ResultView
      result={{
        ...gate5ExplainResponse,
        bullets: [{ text: "Repeated source ids stay display-only.", source_ids: ["thread-post", "thread-post"] }],
        trace: {
          ...gate5ExplainResponse.trace,
          warnings: ["same warning", "same warning"],
          guardrail_flags: ["unknown_citation", "unknown_citation"],
        },
      }}
    />,
  );

  const messages = errorSpy.mock.calls.flat().map(String).join("\n");
  expect(messages).not.toContain("Encountered two children with the same key");
  expect(screen.getAllByLabelText("Citation thread-post: Thread context from Bluesky")).toHaveLength(2);
});

test("surfaces missing or invalid API error payloads with a useful fallback", async () => {
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 502 }));

  await expect(
    explainPost({
      post_url: "https://bsky.app/profile/bsky.app/post/3mk6ipt5iv22y",
      provider: "openai",
      include_trace: true,
    }),
  ).rejects.toThrow("Request failed with status 502.");
});
