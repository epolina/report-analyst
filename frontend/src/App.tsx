// Chat-first layout: the chat column, and a Reports drawer on the
// right. Evidence in an Answer opens its report in the drawer at the quoted page.
import { useEffect, useState } from "react";
import { isProcessing, listReports, type ChatEvidence, type Report } from "./api";
import { ChatComposer, ChatThread, useChat } from "./ChatPanel";
import { ADD_REPORT } from "./options";
import { ReportsDrawer } from "./ReportsDrawer";
import { UploadDialog } from "./UploadDialog";
import { Button, EmptyState, Shell, TopBarButton } from "./ui";

// While a report is processing, the list is fetched this often to follow its status.
const POLL_MS = 3000;

export default function App() {
  const [reports, setReports] = useState<Report[]>();
  const [error, setError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>();
  const [focusedEvidence, setFocusedEvidence] = useState<ChatEvidence>();
  const chat = useChat();

  function refreshReports() {
    listReports()
      .then((loadedReports) => {
        setReports(loadedReports);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }

  useEffect(refreshReports, []);

  const allReports = reports ?? [];
  const processingReport = allReports.find(isProcessing);
  const anyProcessing = processingReport !== undefined;
  const anyFailed = allReports.some((r) => r.status === "failed");
  const selectedReport = allReports.find((r) => r.report_id === selectedId);

  // Follow a processing report until it's ready or failed.
  useEffect(() => {
    if (!anyProcessing) return;
    const timer = setInterval(refreshReports, POLL_MS);
    return () => clearInterval(timer);
  }, [anyProcessing]);

  // Escape closes the drawer, unless the upload dialog is up (it handles its own Escape).
  useEffect(() => {
    if (!drawerOpen || uploadOpen) return;
    const onKeyDown = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen, uploadOpen]);

  function openEvidence(evidence: ChatEvidence) {
    setFocusedEvidence(evidence);
    setSelectedId(evidence.report_id);
    setDrawerOpen(true);
  }

  function selectReport(reportId: string | undefined) {
    setFocusedEvidence(undefined);
    setSelectedId(reportId);
  }

  return (
    <Shell
      brand="Report analyst"
      drawerOpen={drawerOpen}
      drawerWide={selectedReport !== undefined}
      drawer={
        <ReportsDrawer
          reports={allReports}
          error={error}
          processingReport={processingReport}
          selectedReport={selectedReport}
          focusedEvidence={focusedEvidence}
          onSelect={selectReport}
          onAdd={() => setUploadOpen(true)}
          onRetried={refreshReports}
          onAsk={(report) => {
            chat.scopeToReport(report);
            setDrawerOpen(false);
          }}
        />
      }
      actions={
        <>
          <TopBarButton disabled={!chat.turns.length || chat.busy} onClick={chat.newChat}>
            New chat
          </TopBarButton>
          <TopBarButton
            pressed={drawerOpen}
            aria-controls="ui-drawer"
            count={reports?.length}
            dot={
              anyFailed
                ? { tone: "bad", label: "A report failed" }
                : anyProcessing
                  ? { tone: "busy", label: "A report is processing" }
                  : undefined
            }
            onClick={() => setDrawerOpen((open) => !open)}
          >
            Reports
          </TopBarButton>
        </>
      }
      dock={allReports.length > 0 && <ChatComposer chat={chat} reports={allReports} />}
    >
      {reports && !allReports.length && (
        <EmptyState
          title="Add your first annual report"
          action={
            <Button variant="primary" onClick={() => setUploadOpen(true)}>
              {ADD_REPORT}
            </Button>
          }
        >
          Add a PDF and it's read once. Then you can ask questions about it and browse the FTE and sustainability goals
          it contains.
        </EmptyState>
      )}
      <ChatThread chat={chat} reports={allReports} onOpenEvidence={openEvidence} />
      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={(report) => {
          refreshReports();
          setSelectedId(report.report_id);
          setDrawerOpen(true);
        }}
      />
    </Shell>
  );
}
