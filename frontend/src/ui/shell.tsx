// The app frame and the empty state.
import { type ReactNode } from "react";
import "./shell.css";

// The app frame: top bar, a scrolling centre column, a dock under it, and a drawer on the right
// that slides open beside the chat. `drawerWide` widens it for content with a page viewer.
export function Shell({
  brand,
  actions,
  dock,
  drawer,
  drawerOpen = false,
  drawerWide = false,
  children,
}: {
  brand: string;
  actions?: ReactNode;
  dock?: ReactNode;
  drawer?: ReactNode;
  drawerOpen?: boolean;
  drawerWide?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="ui-shell" data-drawer={!drawerOpen ? "closed" : drawerWide ? "wide" : "open"}>
      <div className="ui-shell-main">
        <header className="ui-topbar">
          <span className="ui-brand">{brand}</span>
          {actions}
        </header>
        <main className="ui-main">
          <div className="ui-column">{children}</div>
        </main>
        {dock && <div className="ui-dock">{dock}</div>}
      </div>
      {/* Kept in the DOM while closed so it can slide; inert keeps it out of tab order. */}
      <aside className="ui-drawer" id="ui-drawer" aria-label="Reports" inert={!drawerOpen}>
        {drawer}
      </aside>
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children: ReactNode; action?: ReactNode }) {
  return (
    <section className="ui-empty">
      <h2>{title}</h2>
      <p>{children}</p>
      {action}
    </section>
  );
}
