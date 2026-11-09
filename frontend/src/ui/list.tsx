// The Reports list: its top-bar tab, the drawer pane, the add button, status, filters and table.
import { useState, type ComponentProps, type ReactNode } from "react";
import { ICONS } from "./icons";
import "./list.css";

type Tone = "ok" | "busy" | "bad";

type TopBarButtonProps = Omit<ComponentProps<"button">, "className" | "type"> & {
  pressed?: boolean;
  count?: number;
  dot?: { tone: Tone; label: string };
};

// A quiet top-bar button. With `pressed` it toggles something (the drawer) and shows it's on.
// `dot` flags something worth a look inside, e.g. a failed report.
export function TopBarButton({ pressed, count, dot, children, ...props }: TopBarButtonProps) {
  return (
    <button className="ui-top-bar-button" type="button" aria-pressed={pressed} {...props}>
      {children}
      {count !== undefined && <span className="ui-top-bar-button-count">{count}</span>}
      {dot && <span className="ui-dot" data-tone={dot.tone} role="img" aria-label={dot.label} title={dot.label} />}
    </button>
  );
}

// A coloured dot and a short label: green for done, pulsing amber for in progress, red for failed.
export function Status({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className="ui-status">
      <span className="ui-dot" data-tone={tone} aria-hidden="true" />
      {children}
    </span>
  );
}

// Grey lines standing in for text that isn't there yet.
export function Skeleton() {
  return (
    <div className="ui-skeleton" aria-hidden="true">
      <span />
      <span />
      <span />
    </div>
  );
}

// A drawer panel with its heading, an optional back link above it and a muted line under it.
export function Pane({
  title,
  subtitle,
  back,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  back?: { label: string; onClick: () => void };
  children: ReactNode;
}) {
  return (
    <section className="ui-pane">
      {back && (
        <button className="ui-back" type="button" onClick={back.onClick}>
          {ICONS.back}
          {back.label}
        </button>
      )}
      <h2>{title}</h2>
      {subtitle && <p className="ui-pane-subtitle">{subtitle}</p>}
      {children}
    </section>
  );
}

// A wide dashed button for adding a file.
export function AddFileButton({
  children,
  disabled,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button className="ui-add-file-button" type="button" disabled={disabled} onClick={onClick}>
      {ICONS.upload}
      <span>{children}</span>
    </button>
  );
}

type SelectProps = Omit<ComponentProps<"select">, "className"> & { options: (string | number)[]; allLabel: string };

// A native select whose first option (value "") means "any".
export function Select({ options, allLabel, ...props }: SelectProps) {
  return (
    <select className="ui-select" {...props}>
      <option value="">{allLabel}</option>
      {options.map((option) => (
        <option key={option}>{option}</option>
      ))}
    </select>
  );
}

// Side-by-side filters: a wide first control and a narrow second one.
export function Filters({ children }: { children: ReactNode }) {
  return <div className="ui-filters">{children}</div>;
}

export function EmptyText({ children }: { children: ReactNode }) {
  return <p className="ui-empty-text">{children}</p>;
}

export type TableGroup = { key: string; label: string; rows: { key: string; cells: ReactNode[] }[] };

// A table of rows grouped under collapsible headings, each heading showing its row count.
// With `onSelect`, rows are clickable (mouse, Enter or Space).
export function GroupTable({ groups, onSelect }: { groups: TableGroup[]; onSelect?: (key: string) => void }) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  const toggle = (key: string) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });

  return (
    <table className="ui-table">
      {groups.map((group) => {
        const open = !collapsedGroups.has(group.key);
        return (
          <tbody key={group.key}>
            <tr className="ui-table-group">
              <td colSpan={groups[0]?.rows[0]?.cells.length ?? 1}>
                <button type="button" aria-expanded={open} onClick={() => toggle(group.key)}>
                  {ICONS.chevron}
                  <span>{group.label}</span>
                  <span className="ui-table-count">{group.rows.length}</span>
                </button>
              </td>
            </tr>
            {open &&
              group.rows.map((row) => (
                <tr
                  key={row.key}
                  className="ui-table-row"
                  tabIndex={onSelect ? 0 : undefined}
                  onClick={onSelect && (() => onSelect(row.key))}
                  onKeyDown={
                    onSelect &&
                    ((e) => {
                      if (e.key !== "Enter" && e.key !== " ") return;
                      e.preventDefault();
                      onSelect(row.key);
                    })
                  }
                >
                  {row.cells.map((cell, i) => (
                    <td key={i}>{cell}</td>
                  ))}
                </tr>
              ))}
          </tbody>
        );
      })}
    </table>
  );
}
