// The Reports drawer: the list with its filters, or one report with its FTE, goals and PDF.
import { useEffect, useState } from "react";
import {
  getReport,
  isProcessing,
  retryReport,
  type ChatEvidence,
  type Report,
  type ReportDetail,
  type ReportStatus,
} from "./api";
import { failureMessage } from "./messages";
import { ADD_REPORT, ALL_COMPANIES, ANY_YEAR, companiesOf, unique, yearsOf } from "./options";
import { ReportView } from "./ReportView";
import {
  Button,
  AddFileButton,
  EmptyText,
  Filters,
  GroupTable,
  Note,
  Pane,
  Progress,
  Select,
  Skeleton,
  Status,
  type TableGroup,
} from "./ui";

const STATUS_BADGES: Record<ReportStatus, { tone: "ok" | "busy" | "bad"; label: string }> = {
  processing: { tone: "busy", label: "Processing" },
  success: { tone: "ok", label: "Ready" },
  failed: { tone: "bad", label: "Failed" },
};

const statusBadge = (r: Report) => <Status tone={STATUS_BADGES[r.status].tone}>{STATUS_BADGES[r.status].label}</Status>;

// Reports grouped by Company (A–Z), newest year first within each.
function groupByCompany(reports: Report[]): TableGroup[] {
  return unique(reports.map((r) => r.company_name))
    .sort((a, b) => a.localeCompare(b))
    .map((company) => ({
      key: company,
      label: company,
      rows: reports
        .filter((r) => r.company_name === company)
        .sort((a, b) => b.reporting_year - a.reporting_year)
        .map((r) => ({ key: r.report_id, cells: [r.reporting_year, statusBadge(r)] })),
    }));
}

// Uploads and retries wait while a report is processing; this says why.
function BusyNote({ report }: { report?: Report }) {
  return (
    report && (
      <EmptyText>
        One report at a time: {report.company_name} {report.reporting_year} is processing.
      </EmptyText>
    )
  );
}

export function ReportsDrawer({
  reports,
  error,
  processingReport,
  selectedReport,
  focusedEvidence,
  onSelect,
  onAdd,
  onRetried,
  onAsk,
}: {
  reports: Report[];
  error: string; // why the list couldn't be loaded
  processingReport?: Report;
  selectedReport?: Report;
  focusedEvidence?: ChatEvidence; // Evidence clicked in the chat, shown at its page
  onSelect: (reportId: string | undefined) => void;
  onAdd: () => void;
  onRetried: () => void;
  onAsk: (report: ReportDetail) => void;
}) {
  // Kept here, not in the list, so the filters survive opening a report and coming back.
  const [companyFilter, setCompanyFilter] = useState("");
  const [yearFilter, setYearFilter] = useState("");

  if (selectedReport) {
    return (
      <ReportPane
        report={selectedReport}
        processingReport={processingReport}
        focusedEvidence={focusedEvidence}
        onBack={() => onSelect(undefined)}
        onRetried={onRetried}
        onAsk={onAsk}
      />
    );
  }

  const groups = groupByCompany(
    reports.filter(
      (r) =>
        (!companyFilter || r.company_name === companyFilter) &&
        (!yearFilter || String(r.reporting_year) === yearFilter),
    ),
  );
  return (
    <Pane title="Reports">
      <AddFileButton disabled={processingReport !== undefined} onClick={onAdd}>
        {ADD_REPORT}
      </AddFileButton>
      <BusyNote report={processingReport} />
      {error && <Note tone="bad">{error}</Note>}
      {reports.length > 0 && (
        <>
          <Filters>
            <Select
              aria-label="Filter by company"
              allLabel={ALL_COMPANIES}
              options={companiesOf(reports)}
              value={companyFilter}
              onChange={(e) => setCompanyFilter(e.target.value)}
            />
            <Select
              aria-label="Filter by year"
              allLabel={ANY_YEAR}
              options={yearsOf(reports)}
              value={yearFilter}
              onChange={(e) => setYearFilter(e.target.value)}
            />
          </Filters>
          {groups.length ? (
            <GroupTable groups={groups} onSelect={onSelect} />
          ) : (
            <EmptyText>No reports match. Clear the filters or add a PDF.</EmptyText>
          )}
        </>
      )}
    </Pane>
  );
}

// One report: its status, Retry when it failed, and its FTE, goals and PDF once it's ready.
function ReportPane({
  report,
  processingReport,
  focusedEvidence,
  onBack,
  onRetried,
  onAsk,
}: {
  report: Report;
  processingReport?: Report;
  focusedEvidence?: ChatEvidence;
  onBack: () => void;
  onRetried: () => void;
  onAsk: (report: ReportDetail) => void;
}) {
  const [detailLoad, setDetailLoad] = useState<{ key: string; detail?: ReportDetail; error?: string }>();
  const [retryFailure, setRetryFailure] = useState<{ id: string; message: string }>();

  // Load the report's facts once it's ready, also when it turns ready while open. Keyed by
  // the PDF's hash too, so a replaced report never shows its old facts.
  const detailKey = report.status === "success" ? `${report.report_id}:${report.sha256}` : undefined;
  const reportId = report.report_id;
  useEffect(() => {
    if (!detailKey) return;
    let isCurrent = true; // a load that answers after the user moved on is dropped
    getReport(reportId)
      .then((loadedDetail) => isCurrent && setDetailLoad({ key: detailKey, detail: loadedDetail }))
      .catch((e: Error) => isCurrent && setDetailLoad({ key: detailKey, error: e.message }));
    return () => {
      isCurrent = false;
    };
  }, [detailKey, reportId]);
  const currentLoad = detailKey && detailLoad?.key === detailKey ? detailLoad : undefined;
  const detail = currentLoad?.detail;
  const detailError = currentLoad?.error;
  const retryError = retryFailure?.id === reportId ? retryFailure.message : undefined;

  function retry() {
    setRetryFailure(undefined);
    retryReport(reportId)
      .then(onRetried)
      .catch((e: Error) => setRetryFailure({ id: reportId, message: e.message }));
  }

  return (
    <Pane
      title={`${report.company_name} ${report.reporting_year}`}
      subtitle={
        <>
          {statusBadge(report)} · {report.pages} pages
        </>
      }
      back={{ label: "All reports", onClick: onBack }}
    >
      {isProcessing(report) && (
        <>
          <EmptyText>Reading the report. Evidence and the PDF appear here when it's ready.</EmptyText>
          <Skeleton />
        </>
      )}
      {report.status === "failed" && (
        <>
          <Note tone="bad">{failureMessage(report)}</Note>
          <div>
            <Button disabled={processingReport !== undefined} onClick={retry}>
              Retry
            </Button>
          </div>
          <BusyNote report={processingReport} />
          {retryError && <Note tone="bad">{retryError}</Note>}
        </>
      )}
      {detailError && <Note tone="bad">{detailError}</Note>}
      {report.status === "success" && !detail && !detailError && (
        <Progress label="Loading the FTE and sustainability goals" />
      )}
      {detail && (
        <ReportView
          // New focused Evidence (another one clicked in the chat) starts the view afresh.
          key={`${detail.report_id}:${focusedEvidence?.quote}`}
          report={detail}
          focusedEvidence={focusedEvidence?.report_id === detail.report_id ? focusedEvidence : undefined}
          onAsk={() => onAsk(detail)}
        />
      )}
    </Pane>
  );
}
