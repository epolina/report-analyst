// One ready report: its facts on the left and the page holding the selected Evidence on the right.
import { useState } from "react";
import { pageImageUrl, type Evidence, type ReportDetail } from "./api";
import { Button, EmptyText, Fact, PageViewer, Section, Split } from "./ui";

const formatNumber = (n: number) => n.toLocaleString("en-US");

// "Deadline 2030 · baseline 2016", leaving out what the report doesn't state.
const goalMeta = (g: ReportDetail["goals"][number]) =>
  [g.deadline && `Deadline ${g.deadline}`, g.baseline && `baseline ${g.baseline}`].filter(Boolean).join(" · ") ||
  undefined;

// One report: its facts on the left, each a button that shows its page with the evidence's
// passage highlighted on the right. `focus` opens a chat Answer's Evidence
// instead of the first fact. Keyed by report and focus, so each starts fresh.
export function ReportView({ report, focus, onAsk }: { report: ReportDetail; focus?: Evidence; onAsk: () => void }) {
  const [shown, setShown] = useState<Evidence | undefined>(focus ?? report.fte?.evidence ?? report.goals[0]?.evidence);
  const [page, setPage] = useState(shown?.page ?? 1);
  const show = (evidence: Evidence) => {
    setShown(evidence);
    setPage(evidence.page);
  };

  const onEvidencePage = shown !== undefined && page === shown.page;
  const hint = !shown
    ? undefined
    : onEvidencePage
      ? "The highlighted passage holds the quoted evidence."
      : `Evidence is on page ${shown.page}.`;

  const facts = (
    <>
      <Button onClick={onAsk}>Ask about this report</Button>
      <Section title="Employees (FTE)">
        {report.fte ? (
          <Fact
            figure
            title={formatNumber(report.fte.amount)}
            quote={report.fte.evidence.quote}
            page={report.fte.evidence.page}
            selected={shown === report.fte.evidence}
            onSelect={() => report.fte && show(report.fte.evidence)}
          />
        ) : (
          <EmptyText>No FTE figure found in this report.</EmptyText>
        )}
      </Section>
      <Section title="Sustainability goals">
        {report.goals.length ? (
          report.goals.map((g, i) => (
            <Fact
              key={i}
              title={g.title}
              meta={goalMeta(g)}
              quote={g.evidence.quote}
              page={g.evidence.page}
              selected={shown === g.evidence}
              onSelect={() => show(g.evidence)}
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
      left={facts}
      right={
        report.pages > 0 && (
          <PageViewer
            title={`${report.company_name} · Annual report ${report.reporting_year}`}
            page={page}
            pageCount={report.pages}
            src={pageImageUrl(report.report_id, page)}
            boxes={onEvidencePage ? shown.boxes : []}
            hint={hint}
            onPage={setPage}
          />
        )
      }
    />
  );
}
