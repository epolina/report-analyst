// What the user reads for each code the backend sends. The backend sends codes, never copy, so
// all wording lives here; a new code doesn't compile until it has its message.
import type { components } from "./api.gen";

type Schemas = components["schemas"];
type Report = Schemas["Report"];
// Any error body: the code, plus the fields some codes carry.
export type ErrorBody = Schemas["ErrorOut"] & Partial<Schemas["ExistingReportOut"] & Schemas["TooLargeOut"]>;

const UNREADABLE_PDF = "The PDF couldn't be read. Is it damaged?";
const reportLabel = (r: Report) => `${r.company_name} ${r.reporting_year}`;

export const ERROR_MESSAGES: Record<Schemas["ErrorCode"], (body: ErrorBody) => string> = {
  report_not_found: () => "There's no such report.",
  page_not_found: () => "There's no such page.",
  conversation_not_found: () => "There's no such conversation.",
  not_failed: () => "Only a failed report can be retried.",
  answer_failed: () => "Couldn't answer just now. Try again.",
  file_too_large: (body) => `The file is larger than ${body.max_upload_mb} MB.`,
  not_a_pdf: () => "The file isn't a PDF.",
  unreadable_pdf: () => UNREADABLE_PDF,
  still_processing: (body) => `${reportLabel(body.existing!)} is still processing. Replace it once it's ready.`,
  same_file: (body) => `You've already uploaded this document as ${reportLabel(body.existing!)}.`,
  same_company_year: (body) => `There's already a report for ${reportLabel(body.existing!)}.`,
};

export const FAILURE_MESSAGES: Record<Schemas["ReportFailure"], string> = {
  unreadable_pdf: UNREADABLE_PDF,
  facts_failed: "Couldn't extract the FTE and goals.",
  interrupted: "Processing was interrupted.",
  unexpected: "Something went wrong while processing the report.",
};

export const failureMessage = (r: Report) => (r.failure ? FAILURE_MESSAGES[r.failure] : "Processing failed.");

// `missing` is what the Question named that no stored report has, for no_matching_report.
export const NOT_FOUND_MESSAGES: Record<
  Schemas["NotFoundReason"],
  (missing: string[]) => { title: string; note?: string }
> = {
  not_in_report: () => ({ title: "Not in the extracted facts" }),
  report_not_ready: () => ({ title: "Report not ready", note: "Ask again once the report is Ready." }),
  no_report: () => ({ title: "No report yet", note: "Add a report PDF first." }),
  no_matching_report: (missing) => ({
    title: "No matching report",
    note: missing.length
      ? `There's no report for ${missing.join(", ")}. Add it, or ask about a stored one.`
      : "Name a stored Company, and its year if it has several reports.",
  }),
  unsupported_topic: () => ({
    title: "Not supported",
    note: "Sorry, we only support questions about the FTE and sustainability goals.",
  }),
};
