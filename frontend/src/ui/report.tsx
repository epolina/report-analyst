// One report: titled sections, facts with their Evidence, and the page viewer beside them.
import { type ReactNode } from "react";
import { ICONS } from "./icons";
import "./report.css";

// A titled group inside a pane, e.g. "Employees (FTE)".
export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="ui-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

// One fact with its Evidence, as a button that shows its page in the viewer: a heading (large
// for a figure), a muted line, the quote and its page.
export function Fact({
  title,
  meta,
  quote,
  page,
  figure,
  selected,
  onSelect,
}: {
  title: ReactNode;
  meta?: ReactNode;
  quote: string;
  page: number;
  figure?: boolean;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button className="ui-fact" type="button" data-figure={figure} aria-pressed={selected} onClick={onSelect}>
      <span className="ui-fact-title">{title}</span>
      {meta && <span className="ui-fact-meta">{meta}</span>}
      <span className="ui-quote">{quote}</span>
      <span className="ui-fact-page">Page {page}</span>
    </button>
  );
}

// Two columns: a narrow one on the left (the facts) and a wide one on the right (the page).
export function Split({ left, right }: { left: ReactNode; right: ReactNode }) {
  return (
    <div className="ui-split">
      <div className="ui-split-left">{left}</div>
      <div className="ui-split-right">{right}</div>
    </div>
  );
}

// A highlight on a page, as fractions of the page size from its top-left corner.
export type Box = { x: number; y: number; width: number; height: number };

const percent = (fraction: number) => `${fraction * 100}%`;

// One page of a document as an image, with its title and previous/next buttons above it and
// `boxes` highlighted over it.
export function PageViewer({
  title,
  page,
  pageCount,
  src,
  boxes,
  hint,
  onPage,
}: {
  title: string;
  page: number;
  pageCount: number;
  src: string;
  boxes: Box[];
  hint?: ReactNode;
  onPage: (page: number) => void;
}) {
  return (
    <div className="ui-viewer">
      <div className="ui-viewer-bar">
        <span className="ui-viewer-title">
          {ICONS.file}
          {title}
        </span>
        <span className="ui-viewer-nav">
          <button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => onPage(page - 1)}>
            {ICONS.back}
          </button>
          <span>
            Page <b>{page}</b> of {pageCount}
          </span>
          <button type="button" aria-label="Next page" disabled={page >= pageCount} onClick={() => onPage(page + 1)}>
            {ICONS.chevron}
          </button>
        </span>
      </div>
      <div className="ui-viewer-page">
        <img src={src} alt={`${title}, page ${page}`} />
        {boxes.map((b, i) => (
          <mark
            key={i}
            // Geometry comes from the data, so it's the one inline style.
            style={{ left: percent(b.x), top: percent(b.y), width: percent(b.width), height: percent(b.height) }}
          />
        ))}
      </div>
      {hint && <p className="ui-viewer-hint">{hint}</p>}
    </div>
  );
}
