// Calls to the backend. Types come from its OpenAPI schema: run `npm run gen:api` after
// changing a backend model.
import type { components } from "./api.gen";
import { ERROR, type ErrorBody } from "./messages";

type Schemas = components["schemas"];
export type Report = Schemas["Report"];
export type ReportStatus = Schemas["ReportStatus"];
export type ReportDetail = Schemas["ReportDetail"];
export type Evidence = Schemas["Evidence"];
export type Duplicate = Schemas["ExistingOut"];
export type ErrorCode = Schemas["ErrorCode"];
export type OnDuplicate = Schemas["OnDuplicate"];
export type Scope = Schemas["Scope"];
export type Turn = Schemas["Turn"];
export type ChatEvidence = Schemas["ChatEvidence"];
export type ChatReply = Schemas["ChatReply"];
export type Conversation = Schemas["Conversation"];

// Keeps the status and body, so a caller can act on an expected error like the 409 duplicate.
// The message is for the user, so callers show it as is.
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly body: ErrorBody | null,
  ) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init).catch(() => {
    throw new ApiError("Couldn't reach the server. Check your connection and try again.", 0, null);
  });
  if (!res.ok) {
    // Errors raised on purpose have a `code`; FastAPI's own 422 has a `detail` list instead.
    const body = await res.json().catch(() => null);
    const code: ErrorCode | undefined = body?.code;
    throw new ApiError(
      code ? ERROR[code](body) : `Something went wrong (${res.status}). Try again.`,
      res.status,
      code ? body : null,
    );
  }
  return res.json();
}

export function uploadReport(file: File, company: string, reportingYear: number, onDuplicate?: OnDuplicate) {
  const form = new FormData();
  form.append("file", file);
  form.append("company", company);
  form.append("reporting_year", String(reportingYear));
  if (onDuplicate) form.append("on_duplicate", onDuplicate);
  return call<Report>("/uploads", { method: "POST", body: form });
}

// A background job is extracting the report's text or facts.
export const isProcessing = (r: Report) => r.status === "processing";

export function retryReport(reportId: string) {
  return call<Report>(`/reports/${reportId}/retry`, { method: "POST" });
}

export function listReports() {
  return call<Report[]>("/reports");
}

export function getReport(reportId: string) {
  return call<ReportDetail>(`/reports/${reportId}`);
}

// A page of a report as an image, for an <img> src. Rendered once, then served from disk.
export function pageImageUrl(reportId: string, page: number) {
  return `/api/reports/${reportId}/pages/${page}`;
}

// Ask a Question; a null conversation starts a new one. Takes about 5-15 s.
export function askQuestion(question: string, scope: Scope, conversationId: string | null) {
  return call<ChatReply>("/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, scope, conversation_id: conversationId }),
  });
}

export function getConversation(conversationId: string) {
  return call<Conversation>(`/conversations/${conversationId}`);
}
