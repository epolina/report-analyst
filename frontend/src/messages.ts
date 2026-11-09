// What the user reads for each code the backend sends. The backend sends codes, never copy, so
// all wording lives here; a new code doesn't compile until it has its message.
import type { components } from "./api.gen";

type Schemas = components["schemas"];
type Report = Schemas["Report"];
// Any error body: the code, plus the fields some codes carry.
export type ErrorBody = Schemas["ErrorOut"] & Partial<Schemas["ExistingOut"] & Schemas["TooLargeOut"]>;

const UNREADABLE_PDF = "The PDF couldn't be read. Is it damaged?";
const label = (r: Report) => `${r.company_name} ${r.year}`;

export const ERROR: Record<Schemas["ErrorCode"], (e: ErrorBody) => string> = {
  report_not_found: () => "There's no such report.",
  page_not_found: () => "There's no such page.",
  conversation_not_found: () => "There's no such conversation.",
  not_failed: () => "Only a failed report can be retried.",
  answer_failed: () => "Couldn't answer just now. Try again.",
  file_too_large: (e) => `The file is larger than ${e.max_upload_mb} MB.`,
  not_a_pdf: () => "The file isn't a PDF.",
  unreadable_pdf: () => UNREADABLE_PDF,
  still_processing: (e) => `${label(e.existing!)} is still processing. Replace it once it's ready.`,
  same_file: (e) => `You've already uploaded this document as ${label(e.existing!)}.`,
  same_company_year: (e) => `There's already a report for ${label(e.existing!)}.`,
};

export const FAILURE: Record<Schemas["ReportFailure"], string> = {
  unreadable_pdf: UNREADABLE_PDF,
  facts_failed: "Couldn't extract the FTE and goals.",
  interrupted: "Processing was interrupted.",
  unexpected: "Something went wrong while processing the report.",
};

export const failureMessage = (r: Report) => (r.failure ? FAILURE[r.failure] : "Processing failed.");

export const NOT_FOUND: Record<Schemas["NotFoundReason"], { title: string; note?: string }> = {
  not_in_report: { title: "No matching passage" },
  report_not_ready: { title: "Report not searched", note: "Ask again once the report is Ready." },
  no_report: { title: "No report searched", note: "Add that report, or change the Company or year below." },
};
