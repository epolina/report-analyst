// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import App from "./App";

const REPORT = {
  report_id: "r1",
  company_name: "Shell",
  reporting_year: 2024,
  sha256: "abc",
  page_count: 1,
  status: "success",
  failure: null,
};
const REPLY = {
  conversation_id: "c1",
  question: "How many FTE?",
  scope: { company_name: "Shell", reporting_year: 2024 },
  answer: {
    kind: "answer",
    text: "Shell had 12,345 FTE.",
    reason: null,
    evidence: [{ ...REPORT, page: 1, quote: "We employed 12,345 FTEs.", boxes: [] }],
  },
};

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

// jsdom has no scrolling. Recent Chromium returns a Promise from scrollIntoView, as here; an
// effect that returned it crashed the page on "New chat".
Element.prototype.scrollIntoView = (() => Promise.resolve()) as unknown as () => void;

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
});

test("asking, then starting a new chat, keeps the app on screen", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) => (url.endsWith("/chat") ? jsonResponse(200, REPLY) : jsonResponse(200, [REPORT]))),
  );
  render(<App />);

  fireEvent.change(await screen.findByLabelText("Question"), { target: { value: "How many FTE?" } });
  fireEvent.click(screen.getByRole("button", { name: "Ask" }));
  expect(await screen.findByText("Shell had 12,345 FTE.")).toBeTruthy();

  fireEvent.click(screen.getByRole("button", { name: "New chat" }));
  expect(await screen.findByText("What do you want to know?")).toBeTruthy();
});
