// One ready report: its facts on the left and the page holding the selected Evidence on the right.
import { useState } from "react";
import { pageImageUrl, type Evidence, type ReportDetail } from "./api";
import { Button, EmptyText, Fact, PageViewer, Section, Split } from "./ui";

const formatNumber = (n: number) => n.toLocaleString("en-US");

// "Deadline 2030 · baseline 2016", leaving out what the report doesn't state.
const goalYears = (goal: ReportDetail["goals"][number]) =>
  [goal.deadline && `Deadline ${goal.deadline}`, goal.baseline && `baseline ${goal.baseline}`]
    .filter(Boolean)
    .join(" · ") || undefined;

// One report: its facts on the left, each a button that shows its page with the evidence's
// passage highlighted on the right. `focusedEvidence` opens a chat Answer's Evidence
// instead of the first fact. Keyed by report and focus, so each starts fresh.
export function ReportView({
  report,
  focusedEvidence,
  onAsk,
}: {
  report: ReportDetail;
  focusedEvidence?: Evidence;
  onAsk: () => void;
}) {
  const [shownEvidence, setShownEvidence] = useState<Evidence | undefined>(
    focusedEvidence ?? report.fte?.evidence ?? report.goals[0]?.evidence,
  );
  const [page, setPage] = useState(shownEvidence?.page ?? 1);
  const showEvidence = (evidence: Evidence) => {
    setShownEvidence(evidence);
    setPage(evidence.page);
  };

  const onEvidencePage = shownEvidence !== undefined && page === shownEvidence.page;
  const hint = !shownEvidence
    ? undefined
    : onEvidencePage
      ? "The highlighted passage holds the quoted evidence."
      : `Evidence is on page ${shownEvidence.page}.`;

  const factsColumn = (
    <>
      <Button onClick={onAsk}>Ask about this report</Button>
      <Section title="Employees (FTE)">
        {report.fte ? (
          <Fact
            figure
            title={formatNumber(report.fte.amount)}
            quote={report.fte.evidence.quote}
            page={report.fte.evidence.page}
            selected={shownEvidence === report.fte.evidence}
            onSelect={() => report.fte && showEvidence(report.fte.evidence)}
          />
        ) : (
          <EmptyText>No FTE figure found in this report.</EmptyText>
        )}
      </Section>
      <Section title="Sustainability goals">
        {report.goals.length ? (
          report.goals.map((goal, i) => (
            <Fact
              key={i}
              title={goal.title}
              meta={goalYears(goal)}
              quote={goal.evidence.quote}
              page={goal.evidence.page}
              selected={shownEvidence === goal.evidence}
              onSelect={() => showEvidence(goal.evidence)}
            />
          ))
        ) : (
          <EmptyText>No sustainability goals found in this report.</EmptyText>
        )}
      </Section>
    </>
  );

  return (
    <Split
      left={factsColumn}
      right={
        report.pages > 0 && (
          <PageViewer
            title={`${report.company_name} · Annual report ${report.reporting_year}`}
            page={page}
            pageCount={report.pages}
            src={pageImageUrl(report.report_id, page)}
            boxes={onEvidencePage ? shownEvidence.boxes : []}
            hint={hint}
            onPageChange={setPage}
          />
        )
      }
    />
  );
}
