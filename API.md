# API

> **DRAFT.** Shapes will change as we build. Refine a section here first, then change the code to match. Terms follow UBIQUITOUS_LANGUAGE.md. JSON is snake_case.

## Conventions

- The backend serves routes at the root (`/uploads`). The browser calls them under `/api` (`/api/uploads`); Vite in dev and nginx in Docker strip the prefix.
- Frontend types are generated from the backend's OpenAPI schema (`npm run gen:api` in `frontend/`). This file describes intent; the generated types are what the code checks against.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/uploads` | Multipart: PDF plus Company and Reporting Year, given by the user. Stores the PDF and answers `202` with the report in `processing`; processing runs in the background. A duplicate gets `409` `same_file` or `same_company_year`; for the latter the user then picks `on_duplicate`. `409` `still_processing` when replacing a report that is still processing. |
| `GET` | `/reports` | **Built:** returns the stored `Report[]` (same shape as the upload response) with `status` and `failure`, by Company then year. The frontend polls it every 3 s while any report is processing. |
| `GET` | `/reports/{id}` | **Built:** the report with its FTE and Sustainability Goals (`ReportDetail`). Processing extracts the facts; this only reads them. A processing or failed report gets `fte: null, goals: []`. `404` for an unknown id. |
| `GET` | `/reports/{id}/pages/{n}` | **Built:** page `n` as a JPEG image, 1200 px wide. Rendered with pdfium for every page while processing, then served from disk. `404` for an unknown report or page, or a report still extracting its text. |
| `POST` | `/reports/{id}/retry` | **Built:** `failed` → `processing`, processing the stored PDF again. `202` with the report; `404` for an unknown id; `409` if it didn't fail. A job queued while another runs waits its turn. |
| `POST` | `/chat` | **Built:** ask a Question; `200` with the Turn (`ChatReply`), Not Found included. `404` for an unknown `conversation_id`, `502` if Claude failed (nothing stored). About 5–15 s. |
| `GET` | `/conversations/{id}` | **Built:** the Conversation with all its Turns, to show it after a reload. `404` for an unknown id. |

## Shapes

```jsonc
// POST /uploads  (multipart/form-data)
//   file: PDF, company_name: "Shell", reporting_year: 2024, on_duplicate?: "replace" | "keep_both"
// → 202 Report {report_id, company_name, reporting_year, sha256, pages, status: "processing", failure: null}
// Stores REPORTS_DIR/<report_id>/upload.pdf + metadata.json and queues the report. metadata.json
// also keeps original_filename, for reference only; it isn't returned. A replaced report loses
// its old content here; if the new PDF then fails, the report shows failed and can be retried.
// Errors are {code, ...}; see Rules. Nothing is stored for any of them.
// 409  ExistingReportOut {code, existing: Report}
//   "still_processing": replacing a report that is still processing.
//   "same_file": a stored report has the same sha256. Refused whatever on_duplicate says.
//   "same_company_year": a stored report has the same Company (any case) + year. The client
//     asks "Replace it?" and sends the upload again with on_duplicate=replace (overwrite, keep
//     report_id) or keep_both (new report_id).
//   422  company_name or reporting_year missing/invalid (FastAPI's own {detail: [...]})
//   422  {code: "unreadable_pdf"}: pdfium can't open it; a replaced report stays as it was
//   415  {code: "not_a_pdf"} (%PDF- magic bytes)
//   413  TooLargeOut {code: "file_too_large", max_upload_mb} (MAX_UPLOAD_MB, default 100)

// Report  (GET /reports returns Report[])
{ "report_id": "<uuid>", "company_name": "Shell", "reporting_year": 2024, "sha256": "...", "page_count": 412,
  "status": "processing" | "success" | "failed",
  "failure": null }   // when failed: "unreadable_pdf" | "facts_failed" | "interrupted" | "unexpected"
// Background processing: processing (Mistral OCR, page images, embeddings, then facts with Claude)
// → success. Any error, fact extraction included, → failed with a failure code; Retry runs it all again.
// At start-up, reports left processing by a restart become failed ("interrupted").

// GET /reports/{id} → 200 ReportDetail  (built, see facts/ and reports/service.py)
{ ...Report,                                        // Report includes "page_count"
  "fte": { "amount": 88497, "evidence": {"page": 93, "quote": "..."} } | null,  // null = not found
  "goals": [{ "title": "Net zero Scope 1 and 2 emissions by 2030",   // written by Claude
              "deadline": 2030 | null, "baseline": 2022 | null,
              "evidence": {"page": 142, "quote": "...",         // verbatim; checked against the cited passage
                           "boxes": [PageBox] } }] }             // the boxes of the block(s) holding the quote
// Every quote is checked to occur in a passage on its page (ignoring Markdown and whitespace);
// a fact whose quote doesn't is dropped.

// Quantity
{ "amount": 96000, "unit": "FTE", "currency": null, "scale": null }

// POST /chat
{ "conversation_id": null,                           // null starts a new one
  "question": "Compare the sustainability goals of ABN 2025 and Shell 2025" }
// Claude reads the Fact and the Company-year pairs from the question (and earlier ones, for a
// follow-up); the app finds those reports' extracted Facts; Claude answers from them.
// Only the FTE and Sustainability Goals are supported.
// → 200 ChatReply
{ "conversation_id": "<uuid>",
  "question": "...",
  "reports": [ReportRef],   // the reports it was matched to; shown under the question
  "answer": Answer }

// ReportRef
{ "report_id": "<uuid>", "company_name": "ABN AMRO", "reporting_year": 2025 }

// Answer
{ "kind": "answer", "text": "...", "evidence": [ChatEvidence], "reason": null, "missing": [] }
{ "kind": "not_found", "text": "..." | "", "evidence": [],   // "" unless Claude wrote it
  "reason": "not_in_report"         // the Facts don't state it, or the answer cited none
          | "report_not_ready"      // the reports asked about are processing or failed
          | "no_report"             // nothing is stored yet
          | "no_company_named"      // couldn't tell which Company the question means
          | "no_matching_report"    // a Company or year with no stored report: see missing
          | "unsupported_topic",    // not about the FTE or Sustainability Goals
  "missing": ["ABN AMRO 2023"] }    // for no_matching_report; [] otherwise

// ChatEvidence: a cited Fact's Evidence plus its report, since one Question can cover several
{ "report_id": "<uuid>", "company_name": "Shell", "reporting_year": 2025, "page": 57,
  "quote": "<verbatim>", "boxes": [PageBox] }

// GET /conversations/{id} → 200 { "conversation_id": "<uuid>", "turns": [{question, reports, answer}] }
```

## Rules

- Not Found is a `200` answer, not an error. HTTP errors are for bad input or a broken backend.
- The backend sends codes, never copy. An error is `{"code": ErrorCode, ...}` (`ErrorOut`, `ExistingReportOut`, `TooLargeOut`); `failure` and Not Found `reason` are codes too. The frontend words them all in `src/api/messages.ts`. Only FastAPI's own 422 validation error keeps its `{"detail": [...]}`.
- Answer `text` is plain text. Never HTML.
- When a report is replaced, it keeps its `id`, so old Evidence still resolves.
- The backend detects duplicates (409). The same file is refused; for the same Company and year the user decides: replace, or keep both. "Keep both" means a Company and year can have several reports.
- Company is matched case-insensitively against existing Companies ("shell" → "Shell"); otherwise stored as typed, trimmed.
- One PDF per request. The client loops for several files.

## Open questions

- Should `GET /reports` include `fte_amount` and `goal_count`? Only the table layout needs them.

## Not yet

Push progress (SSE), streaming answers, a conversation list. Add each when the UI needs it.
