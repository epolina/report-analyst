// The chat: the thread of Questions and Answers with their Evidence, and the composer.
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "./controls";
import { ICONS } from "./icons";
import "./chat.css";

// The Questions and Answers, oldest first. Scrolls to the newest when `messageCount` grows, not
// on every render. Announced politely as answers arrive.
export function Thread({ messageCount, children }: { messageCount: number; children: ReactNode }) {
  const endRef = useRef<HTMLDivElement>(null);
  // Braces: an effect's return value is its clean-up, and scrollIntoView may return a Promise.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [messageCount]);
  return (
    <div className="ui-thread" aria-live="polite">
      {children}
      <div ref={endRef} />
    </div>
  );
}

// What to show before the first Question: a heading, a line and suggested Questions.
export function ChatStart({
  title,
  hint,
  suggestions,
  onPick,
}: {
  title: string;
  hint: string;
  suggestions: string[];
  onPick: (question: string) => void;
}) {
  return (
    <section className="ui-chat-start">
      <h2>{title}</h2>
      <p>{hint}</p>
      <div className="ui-chips">
        {suggestions.map((suggestion) => (
          <button key={suggestion} type="button" className="ui-chip" onClick={() => onPick(suggestion)}>
            {suggestion}
          </button>
        ))}
      </div>
    </section>
  );
}

// The user's Question, right-aligned, with the scope it searched under it.
export function Question({ children, meta }: { children: ReactNode; meta?: ReactNode }) {
  return (
    <div className="ui-question">
      <p className="ui-bubble">{children}</p>
      {meta && <p className="ui-question-meta">{meta}</p>}
    </div>
  );
}

// An Answer: its plain text, if any, then its Evidence or Not Found card.
export function Answer({ text, children }: { text: string; children?: ReactNode }) {
  return (
    <div className="ui-answer">
      {text && <p>{text}</p>}
      {children}
    </div>
  );
}

// While an Answer is being written.
export function Thinking({ label }: { label: string }) {
  return (
    <div className="ui-answer ui-thinking" role="status" aria-label={label}>
      <span />
      <span />
    </div>
  );
}

// One verbatim quote: its source, which opens the page, a copy button and the quote itself.
export function EvidenceCard({ source, quote, onOpen }: { source: string; quote: string; onOpen: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = () =>
    navigator.clipboard.writeText(quote).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    });
  return (
    <div className="ui-evidence">
      <div className="ui-evidence-bar">
        <button type="button" className="ui-evidence-source" title="Open this page" onClick={onOpen}>
          {ICONS.file}
          {source}
        </button>
        <span className="ui-evidence-actions">
          <button type="button" className="ui-evidence-copy" onClick={copy}>
            {copied ? "Copied" : "Copy quote"}
          </button>
          <span className="ui-tag">Verbatim</span>
        </span>
      </div>
      <blockquote className="ui-quote">{quote}</blockquote>
    </div>
  );
}

// No Evidence: a muted card saying why.
export function NotFoundCard({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="ui-evidence" data-tone="muted">
      <div className="ui-evidence-bar">
        <span className="ui-evidence-source">
          {ICONS.file}
          {title}
        </span>
        <span className="ui-tag">Not found</span>
      </div>
      {children && <p className="ui-evidence-note">{children}</p>}
    </div>
  );
}

// The question box docked under the chat: a scope line ("Searching …") and a pill input.
export function Composer({
  scope,
  placeholder,
  value,
  disabled,
  busy,
  onChange,
  onSubmit,
}: {
  scope?: ReactNode;
  placeholder: string;
  value: string;
  disabled?: boolean;
  busy?: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const inputId = useId();
  return (
    <form
      className="ui-composer"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim() && !busy) onSubmit();
      }}
    >
      {scope && (
        <div className="ui-scope">
          <span>Searching</span>
          {scope}
        </div>
      )}
      <div className="ui-ask">
        <label htmlFor={inputId} className="ui-visually-hidden">
          Question
        </label>
        <input
          id={inputId}
          name="q"
          type="text"
          placeholder={placeholder}
          autoComplete="off"
          value={value}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        />
        <Button type="submit" variant="primary" disabled={disabled || busy || !value.trim()}>
          Ask
        </Button>
      </div>
    </form>
  );
}
