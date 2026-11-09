// The chat: its Turns, the Question being answered, and the composer.
// `useChat` holds the state; the layout places the thread and the composer in different slots.
import { useEffect, useState } from "react";
import {
  askQuestion,
  getConversation,
  NOT_FOUND_MESSAGES,
  type ChatEvidence,
  type Report,
  type ReportRef,
  type Turn,
} from "../api";
import { Answer, ChatStart, Composer, EvidenceCard, Note, NotFoundCard, Question, Thinking, Thread } from "../ui";

// The open Conversation's id, so a reload shows it again.
const CONVERSATION_KEY = "conversation";
const savedConversationId = {
  get: () => {
    try {
      return localStorage.getItem(CONVERSATION_KEY);
    } catch {
      return null;
    }
  },
  set: (id: string | null) => {
    try {
      if (id) localStorage.setItem(CONVERSATION_KEY, id);
      else localStorage.removeItem(CONVERSATION_KEY);
    } catch {
      // private mode: the chat just isn't restored after a reload
    }
  },
};

// The reports a Question was matched to, shown under it: "ABN AMRO 2025 · Shell 2025".
const reportsLabel = (reports: ReportRef[]) =>
  reports.map((r) => `${r.company_name} ${r.reporting_year}`).join(" · ") || undefined;
const sourceLabel = (e: ChatEvidence) => `${e.company_name} annual report ${e.reporting_year} · p. ${e.page}`;

export function useChat() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string>();
  const [error, setError] = useState("");

  // Show the last Conversation again after a reload. One that's gone starts a fresh chat.
  useEffect(() => {
    const id = savedConversationId.get();
    if (!id) return;
    getConversation(id)
      .then((conversation) => {
        setConversationId(id);
        setTurns(conversation.turns);
      })
      .catch(() => savedConversationId.set(null));
  }, []);

  function ask(question: string) {
    setPendingQuestion(question);
    setError("");
    setDraft("");
    askQuestion(question, conversationId)
      .then((reply) => {
        setConversationId(reply.conversation_id);
        savedConversationId.set(reply.conversation_id);
        setTurns((previousTurns) => [...previousTurns, reply]);
      })
      .catch((e: Error) => {
        setError(e.message);
        setDraft(question);
      })
      .finally(() => setPendingQuestion(undefined));
  }

  function newChat() {
    setConversationId(null);
    savedConversationId.set(null);
    setTurns([]);
    setError("");
  }

  // Start a Question about one report, e.g. from its page in the drawer: the Company and year
  // go first in the composer, and the user types the rest.
  function askAboutReport(report: { company_name: string; reporting_year: number }) {
    setDraft(`${report.company_name} ${report.reporting_year}: `);
  }

  const busy = pendingQuestion !== undefined;
  return {
    turns,
    pendingQuestion,
    busy,
    error,
    draft,
    setDraft,
    ask,
    newChat,
    askAboutReport,
  };
}

type Chat = ReturnType<typeof useChat>;

export function ChatComposer({ chat }: { chat: Chat }) {
  return (
    <Composer
      placeholder="Ask about the FTE or sustainability goals, e.g. How many FTE did Shell have in 2024?"
      value={chat.draft}
      busy={chat.busy}
      onChange={chat.setDraft}
      onSubmit={() => chat.ask(chat.draft.trim())}
    />
  );
}

export function ChatThread({
  chat,
  reports,
  onOpenEvidence,
}: {
  chat: Chat;
  reports: Report[];
  onOpenEvidence: (evidence: ChatEvidence) => void;
}) {
  const { turns, pendingQuestion, busy } = chat;
  return (
    <>
      {reports.length > 0 && !turns.length && !busy && (
        <ChatStart
          title="What do you want to know?"
          hint="Ask about the FTE or the sustainability goals of one report, or compare several. Answers quote the report word for word and name the page."
          suggestions={suggestionsFor(reports)}
          onPick={chat.ask}
        />
      )}
      {(turns.length > 0 || busy) && (
        <Thread messageCount={turns.length * 2 + (busy ? 2 : 0)}>
          {turns.map((t, i) => (
            <TurnView key={i} turn={t} onOpenEvidence={onOpenEvidence} />
          ))}
          {busy && (
            <>
              <Question>{pendingQuestion}</Question>
              <Thinking label="Searching the reports" />
            </>
          )}
        </Thread>
      )}
      {chat.error && <Note tone="bad">{chat.error}</Note>}
    </>
  );
}

// Suggested first Questions, about reports that are there to answer them, and a comparison
// when two Companies are ready.
function suggestionsFor(reports: Report[]) {
  const ready = reports.filter((candidate) => candidate.status === "success");
  const report = ready[0] ?? reports[0];
  const other = ready.find((candidate) => candidate.company_name !== report.company_name);
  return [
    `How many FTE did ${report.company_name} have in ${report.reporting_year}?`,
    `What are ${report.company_name}'s sustainability goals for ${report.reporting_year}?`,
    ...(other
      ? [
          `Compare the sustainability goals of ${report.company_name} ${report.reporting_year} and ${other.company_name} ${other.reporting_year}`,
        ]
      : []),
  ];
}

// One Question and its Answer, with Evidence that opens its page, or why it wasn't found.
function TurnView({ turn, onOpenEvidence }: { turn: Turn; onOpenEvidence: (evidence: ChatEvidence) => void }) {
  const { answer } = turn;
  const notFound = NOT_FOUND_MESSAGES[answer.reason ?? "not_in_report"](answer.missing ?? []);
  return (
    <>
      <Question meta={reportsLabel(turn.reports ?? [])}>{turn.question}</Question>
      <Answer text={answer.text}>
        {answer.kind === "answer" ? (
          answer.evidence.map((e, i) => (
            <EvidenceCard key={i} source={sourceLabel(e)} quote={e.quote} onOpen={() => onOpenEvidence(e)} />
          ))
        ) : (
          <NotFoundCard title={notFound.title}>{notFound.note}</NotFoundCard>
        )}
      </Answer>
    </>
  );
}
