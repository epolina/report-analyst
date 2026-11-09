// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { UploadDialog } from "./UploadDialog";

const REPORT = { report_id: "r1", company_name: "Shell", reporting_year: 2024, sha256: "abc", status: "processing" };
const DUPLICATE = { code: "same_company_year", existing: REPORT };
const SAME_FILE = { code: "same_file", existing: REPORT };

function reply(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status }));
}

// jsdom has <dialog> but not its modal methods.
beforeEach(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fillAndSubmit(onClose = () => {}) {
  const onUploaded = vi.fn();
  render(<UploadDialog open onClose={onClose} onUploaded={onUploaded} />);
  const pdf = new File(["%PDF-1.7"], "shell-2024.pdf", { type: "application/pdf" });
  fireEvent.change(screen.getByLabelText("PDF file"), { target: { files: [pdf] } });
  fireEvent.change(screen.getByLabelText("Company"), { target: { value: " Shell " } });
  fireEvent.change(screen.getByLabelText("Reporting year"), { target: { value: "2024" } });
  fireEvent.click(screen.getByRole("button", { name: "Add report" }));
  return onUploaded;
}

function sent(fetch: ReturnType<typeof vi.fn>, call: number) {
  return Object.fromEntries((fetch.mock.calls[call][1].body as FormData).entries());
}

test("checks the form before sending", () => {
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<UploadDialog open onClose={() => {}} onUploaded={() => {}} />);

  fireEvent.click(screen.getByRole("button", { name: "Add report" }));

  expect(screen.getByRole("alert").textContent).toBe("Choose the PDF to add.");
  expect(fetch).not.toHaveBeenCalled();
});

test("a new report is sent trimmed and handed to onUploaded", async () => {
  const fetch = vi.fn(() => reply(202, REPORT));
  vi.stubGlobal("fetch", fetch);

  const onUploaded = fillAndSubmit();

  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(REPORT));
  expect(sent(fetch, 0)).toMatchObject({ company_name: "Shell", reporting_year: "2024" });
  expect(sent(fetch, 0)).not.toHaveProperty("on_duplicate");
});

test.each([
  ["Replace", "replace"],
  ["Keep both", "keep_both"],
])("a duplicate asks first, then %s resends with on_duplicate=%s", async (button, choice) => {
  const fetch = vi.fn().mockReturnValueOnce(reply(409, DUPLICATE)).mockReturnValueOnce(reply(202, REPORT));
  vi.stubGlobal("fetch", fetch);

  const onUploaded = fillAndSubmit();

  expect((await screen.findByRole("status")).textContent).toBe("There's already a report for Shell 2024. Replace it?");
  expect(onUploaded).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: button }));
  await waitFor(() => expect(onUploaded).toHaveBeenCalledWith(REPORT));
  expect(sent(fetch, 1)).toMatchObject({ on_duplicate: choice });
});

test("the same file can only be dropped", async () => {
  const fetch = vi.fn(() => reply(409, SAME_FILE));
  vi.stubGlobal("fetch", fetch);
  const onClose = vi.fn();

  fillAndSubmit(onClose);

  expect((await screen.findByRole("status")).textContent).toBe("You've already uploaded this document as Shell 2024.");
  expect(screen.queryByRole("button", { name: "Replace" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Keep both" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

test("editing the form drops the duplicate question", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => reply(409, DUPLICATE)),
  );

  fillAndSubmit();
  await screen.findByRole("status");
  fireEvent.change(screen.getByLabelText("Reporting year"), { target: { value: "2025" } });

  expect(screen.queryByRole("status")).toBeNull();
  expect(screen.getByRole("button", { name: "Add report" })).toBeTruthy();
});

test("while the PDF is sent, the dialog can't be closed", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => new Promise(() => {})), // still sending
  );

  fillAndSubmit();

  expect(((await screen.findByRole("button", { name: "Adding…" })) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  expect((screen.getByLabelText("Company") as HTMLInputElement).disabled).toBe(true);
  const escape = new Event("cancel", { cancelable: true });
  screen.getByRole("dialog", { hidden: true }).dispatchEvent(escape);
  expect(escape.defaultPrevented).toBe(true);
});
