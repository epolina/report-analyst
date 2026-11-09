// Chat-first layout: the chat column, and a Reports drawer on the
// right. Evidence in an Answer opens its report in the drawer at the quoted page.
import { useEffect, useState } from "react";
import { isProcessing, listReports, type ChatEvidence, type Report } from "./api";
import { ChatComposer, ChatThread, useChat } from "./ChatPanel";
import { ADD_REPORT } from "./options";
import { ReportsDrawer } from "./ReportsDrawer";
import { UploadDialog } from "./UploadDialog";
import { Button, EmptyState, Shell, Tab } from "./ui";

// While a report is processing, the list is fetched this often to follow its status.
const POLL_MS = 3000;

export default function App() {
  const [reports, setReports] = useState<Report[]>();
  const [error, setError] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [selectedId, setSelectedId] = useState<string>();
  const [focus, setFocus] = useState<ChatEvidence>();
  const chat = useChat();

  function refresh() {
    listReports()
      .then((r) => {
        setReports(r);
        setError("");
      })
      .catch((e: Error) => setError(e.message));
  }

  useEffect(refresh, []);

  const all = reports ?? [];
  const busyReport = all.find(isProcessing);
  const processing = busyReport !== undefined;
  const failed = all.some((r) => r.status === "failed");
  const selected = all.find((r) => r.report_id === selectedId);

  // Follow a processing report until it's ready or failed.
  useEffect(() => {
    if (!processing) return;
    const timer = setInterval(refresh, POLL_MS);
    return () => clearInterval(timer);
  }, [processing]);

  // Escape closes the drawer, unless the upload dialog is up (it handles its own Escape).
  useEffect(() => {
    if (!drawerOpen || uploadOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen, uploadOpen]);

  function openEvidence(evidence: ChatEvidence) {
    setFocus(evidence);
    setSelectedId(evidence.report_id);
    setDrawerOpen(true);
  }

  function selectReport(reportId: string | undefined) {
    setFocus(undefined);
    setSelectedId(reportId);
  }

  return (
    <Shell
      brand="Report analyst"
      drawerOpen={drawerOpen}
      drawerWide={selected !== undefined}
      drawer={
        <ReportsDrawer
          reports={all}
          error={error}
          busyReport={busyReport}
          selected={selected}
          focus={focus}
          onSelect={selectReport}
          onAdd={() => setUploadOpen(true)}
          onRetried={refresh}
          onAsk={(report) => {
            chat.scopeTo(report);
            setDrawerOpen(false);
          }}
        />
      }
      actions={
        <>
          <Tab disabled={!chat.turns.length || chat.busy} onClick={chat.newChat}>
            New chat
          </Tab>
          <Tab
            pressed={drawerOpen}
            aria-controls="ui-drawer"
            count={reports?.length}
            dot={
              failed
                ? { tone: "bad", label: "A report failed" }
                : processing
                  ? { tone: "busy", label: "A report is processing" }
                  : undefined
            }
            onClick={() => setDrawerOpen((o) => !o)}
          >
            Reports
          </Tab>
        </>
      }
      dock={all.length > 0 && <ChatComposer chat={chat} reports={all} />}
    >
      {reports && !all.length && (
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
      <ChatThread chat={chat} reports={all} onOpen={openEvidence} />
      <UploadDialog
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        onUploaded={(report) => {
          refresh();
          setSelectedId(report.report_id);
          setDrawerOpen(true);
        }}
      />
    </Shell>
  );
}
