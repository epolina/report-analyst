// The "Add a report" popup: the user picks the PDF and types the Company and Reporting Year.
import { useState, type FormEvent } from "react";
import { ApiError, uploadReport, type Duplicate, type OnDuplicate, type Report } from "./api";
import { ERROR } from "./messages";
import { Button, Dialog, Field, Note } from "./ui";

// Checked before sending, so the common mistakes don't need a round trip. The backend checks again.
function validate(file: File | undefined, company: string, year: string): string {
  if (!file) return "Choose the PDF to add.";
  if (!company.trim()) return "Enter the company name.";
  if (!/^\d{4}$/.test(year.trim())) return "Enter the reporting year as four digits, like 2024.";
  return "";
}

export function UploadDialog({
  open,
  onClose,
  onUploaded,
}: {
  open: boolean;
  onClose: () => void;
  onUploaded: (report: Report) => void;
}) {
  const [file, setFile] = useState<File>();
  const [company, setCompany] = useState("");
  const [year, setYear] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // Set when the backend says the upload duplicates a stored report. For the same Company and year
  // the user chooses; the exact same file can only be dropped.
  const [duplicate, setDuplicate] = useState<Duplicate>();

  // Any edit means a new upload, so the error and the duplicate question no longer apply.
  function edited() {
    setError("");
    setDuplicate(undefined);
  }

  function close() {
    setFile(undefined);
    setCompany("");
    setYear("");
    edited();
    onClose();
  }

  async function send(onDuplicate?: OnDuplicate) {
    const invalid = validate(file, company, year);
    if (invalid) return setError(invalid);
    setBusy(true);
    try {
      const upload = await uploadReport(file!, company.trim(), Number(year), onDuplicate);
      setBusy(false);
      onUploaded(upload);
      close();
    } catch (err) {
      const code = err instanceof ApiError ? err.body?.code : undefined;
      if (code === "same_file" || code === "same_company_year") setDuplicate((err as ApiError).body as Duplicate);
      else setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (duplicate?.code === "same_file") return close();
    send(duplicate ? "replace" : undefined);
  }

  return (
    <Dialog
      open={open}
      title="Add a report"
      description="Tell us whose report this is. It's read in the background once the PDF is added."
      // Only while the PDF is sent; processing runs in the background and the list shows its status.
      locked={busy}
      onClose={close}
      onSubmit={submit}
      actions={
        busy ? (
          <Button type="submit" variant="primary" disabled>
            Adding…
          </Button>
        ) : duplicate?.code === "same_file" ? (
          <Button type="submit" variant="primary">
            Close
          </Button>
        ) : duplicate ? (
          <>
            <Button onClick={() => send("keep_both")}>Keep both</Button>
            <Button type="submit" variant="primary">
              Replace
            </Button>
          </>
        ) : (
          <>
            <Button onClick={close}>Cancel</Button>
            <Button type="submit" variant="primary">
              Add report
            </Button>
          </>
        )
      }
    >
      <Field
        label="PDF file"
        type="file"
        accept="application/pdf,.pdf"
        disabled={busy}
        // A fresh input each time the dialog opens, since a file input can't be reset by value.
        key={String(open)}
        onChange={(e) => {
          setFile(e.target.files?.[0]);
          edited();
        }}
      />
      <Field
        label="Company"
        placeholder="Shell"
        autoComplete="off"
        disabled={busy}
        value={company}
        onChange={(e) => {
          setCompany(e.target.value);
          edited();
        }}
      />
      <Field
        label="Reporting year"
        placeholder="2024"
        inputMode="numeric"
        maxLength={4}
        disabled={busy}
        value={year}
        onChange={(e) => {
          setYear(e.target.value);
          edited();
        }}
      />
      {duplicate && !busy && (
        <Note tone="warn">
          {duplicate.code === "same_file"
            ? ERROR.same_file(duplicate)
            : `${ERROR.same_company_year(duplicate)} Replace it?`}
        </Note>
      )}
      {error && <Note tone="bad">{error}</Note>}
    </Dialog>
  );
}
