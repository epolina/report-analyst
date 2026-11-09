// The chat: its Turns, the Question being answered, and the scope selects under the composer.
// `useChat` holds the state; the layout places the thread and the composer in different slots.
import { useEffect, useState } from "react";
import { askQuestion, getConversation, type ChatEvidence, type Report, type Scope, type Turn } from "./api";
import { NOT_FOUND } from "./messages";
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
const storage = {
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

const scopeLabel = (s: Scope) => `${s.company ?? ALL_COMPANIES} · ${s.reporting_year ?? ANY_YEAR}`;
const sourceLabel = (e: ChatEvidence) => `${e.company_name} annual report ${e.year} · p. ${e.page}`;

export function useChat() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState<string>();
  const [error, setError] = useState("");
  const [company, setCompany] = useState("");
  const [year, setYear] = useState("");

  // Show the last Conversation again after a reload. One that's gone starts a fresh chat.
  useEffect(() => {
    const id = storage.get();
    if (!id) return;
    getConversation(id)
      .then((c) => {
        setConversationId(id);
        setTurns(c.turns);
      })
      .catch(() => storage.set(null));
  }, []);

  function ask(question: string) {
    const scope = { company: company || null, reporting_year: year ? Number(year) : null };
    setPending(question);
    setError("");
    setDraft("");
    askQuestion(question, scope, conversationId)
      .then((reply) => {
        setConversationId(reply.conversation_id);
        storage.set(reply.conversation_id);
        setTurns((t) => [...t, reply]);
        // The scope it searched, which the Question may have changed, carries over to the next.
        setCompany(reply.scope.company ?? "");
        setYear(reply.scope.reporting_year ? String(reply.scope.reporting_year) : "");
      })
      .catch((e: Error) => {
        setError(e.message);
        setDraft(question);
      })
      .finally(() => setPending(undefined));
  }

  function newChat() {
    setConversationId(null);
    storage.set(null);
    setTurns([]);
    setError("");
  }

  // Ask about one report next, e.g. from its page in the drawer.
  function scopeTo(report: { company_name: string; year: number }) {
    setCompany(report.company_name);
    setYear(String(report.year));
  }

  const busy = pending !== undefined;
  return { turns, pending, busy, error, draft, setDraft, company, setCompany, year, setYear, ask, newChat, scopeTo };
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
            value={chat.company}
            onChange={(e) => chat.setCompany(e.target.value)}
          />
          <Select
            aria-label="Reporting year"
            allLabel={ANY_YEAR}
            options={yearsOf(reports)}
            value={chat.year}
            onChange={(e) => chat.setYear(e.target.value)}
          />
        </>
      }
    />
  );
}

export function ChatThread({
  chat,
  reports,
  onOpen,
}: {
  chat: Chat;
  reports: Report[];
  onOpen: (evidence: ChatEvidence) => void;
}) {
  const { turns, pending, busy } = chat;
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
        <Thread size={turns.length * 2 + (busy ? 2 : 0)}>
          {turns.map((t, i) => (
            <TurnView key={i} turn={t} onOpen={onOpen} />
          ))}
          {busy && (
            <>
              <Question>{pending}</Question>
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
  const r = reports.find((x) => x.status === "success") ?? reports[0];
  return [
    `How much did ${r.company_name} spend on climate change adaptation in ${r.year}?`,
    `How many FTE did ${r.company_name} have in ${r.year}?`,
    `What are ${r.company_name}'s sustainability goals?`,
  ];
}

// One Question and its Answer, with Evidence that opens its page, or why it wasn't found.
function TurnView({ turn, onOpen }: { turn: Turn; onOpen: (evidence: ChatEvidence) => void }) {
  const { answer } = turn;
  const notFound = NOT_FOUND[answer.reason ?? "not_in_report"];
  return (
    <>
      <Question meta={scopeLabel(turn.scope)}>{turn.question}</Question>
      <Answer text={answer.text}>
        {answer.kind === "answer" ? (
          answer.evidence.map((e, i) => (
            <EvidenceCard key={i} source={sourceLabel(e)} quote={e.quote} onOpen={() => onOpen(e)} />
          ))
        ) : (
          <NotFoundCard title={notFound.title}>{notFound.note}</NotFoundCard>
        )}
      </Answer>
    </>
  );
}
