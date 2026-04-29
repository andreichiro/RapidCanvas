import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import App from "./App";

test("renders the T0 application shell", () => {
  render(<App />);

  expect(screen.getByRole("heading", { name: "Bluesky Contextual Post Explainer" })).toBeVisible();
  expect(screen.getByText("T0 scaffold")).toBeVisible();
});
