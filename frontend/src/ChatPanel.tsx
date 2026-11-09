// The chat: its Turns, the Question being answered, and the scope selects under the composer.
// `useChat` holds the state; the layout places the thread and the composer in different slots.
import { useEffect, useState } from "react";
import { askQuestion, getConversation, type ChatEvidence, type Report, type Scope, type Turn } from "./api";
import { NOT_FOUND_MESSAGES } from "./messages";
import { ALL_COMPANIES, ANY_YEAR, companiesOf, yearsOf } from "./options";
import {
  Answer,
  ChatStart,
  Composer,
  EvidenceCard,
  Note,
  NotFoundCard,
  Question,
  Select,
  Thinking,
  Thread,
} from "./ui";

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

const scopeLabel = (s: Scope) => `${s.company_name ?? ALL_COMPANIES} · ${s.reporting_year ?? ANY_YEAR}`;
const sourceLabel = (e: ChatEvidence) => `${e.company_name} annual report ${e.reporting_year} · p. ${e.page}`;

export function useChat() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pendingQuestion, setPendingQuestion] = useState<string>();
  const [error, setError] = useState("");
  const [scopeCompany, setScopeCompany] = useState("");
  const [scopeYear, setScopeYear] = useState("");

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
    const scope = { company_name: scopeCompany || null, reporting_year: scopeYear ? Number(scopeYear) : null };
    setPendingQuestion(question);
    setError("");
    setDraft("");
    askQuestion(question, scope, conversationId)
      .then((reply) => {
        setConversationId(reply.conversation_id);
        savedConversationId.set(reply.conversation_id);
        setTurns((previousTurns) => [...previousTurns, reply]);
        // The scope it searched, which the Question may have changed, carries over to the next.
        setScopeCompany(reply.scope.company_name ?? "");
        setScopeYear(reply.scope.reporting_year ? String(reply.scope.reporting_year) : "");
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

  // Ask about one report next, e.g. from its page in the drawer.
  function scopeToReport(report: { company_name: string; reporting_year: number }) {
    setScopeCompany(report.company_name);
    setScopeYear(String(report.reporting_year));
  }

  const busy = pendingQuestion !== undefined;
  return {
    turns,
    pendingQuestion,
    busy,
    error,
    draft,
    setDraft,
    scopeCompany,
    setScopeCompany,
    scopeYear,
    setScopeYear,
    ask,
    newChat,
    scopeToReport,
  };
}

type Chat = ReturnType<typeof useChat>;

export function ChatComposer({ chat, reports }: { chat: Chat; reports: Report[] }) {
  return (
    <Composer
      placeholder="Ask about a report, e.g. How many FTE did Shell report?"
      value={chat.draft}
      busy={chat.busy}
      onChange={chat.setDraft}
      onSubmit={() => chat.ask(chat.draft.trim())}
      scope={
        <>
          <Select
            aria-label="Company"
            allLabel={ALL_COMPANIES}
            options={companiesOf(reports)}
            value={chat.scopeCompany}
            onChange={(e) => chat.setScopeCompany(e.target.value)}
          />
          <Select
            aria-label="Reporting year"
            allLabel={ANY_YEAR}
            options={yearsOf(reports)}
            value={chat.scopeYear}
            onChange={(e) => chat.setScopeYear(e.target.value)}
          />
        </>
      }
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
          hint="Answers quote the report word for word and name the page."
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

// Suggested first Questions, about a report that is there to answer them.
function suggestionsFor(reports: Report[]) {
  const report = reports.find((candidate) => candidate.status === "success") ?? reports[0];
  return [
    `How much did ${report.company_name} spend on climate change adaptation in ${report.reporting_year}?`,
    `How many FTE did ${report.company_name} have in ${report.reporting_year}?`,
    `What are ${report.company_name}'s sustainability goals?`,
  ];
}

// One Question and its Answer, with Evidence that opens its page, or why it wasn't found.
function TurnView({ turn, onOpenEvidence }: { turn: Turn; onOpenEvidence: (evidence: ChatEvidence) => void }) {
  const { answer } = turn;
  const notFound = NOT_FOUND_MESSAGES[answer.reason ?? "not_in_report"];
  return (
    <>
      <Question meta={scopeLabel(turn.scope)}>{turn.question}</Question>
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
