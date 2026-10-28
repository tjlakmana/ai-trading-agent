import type { ReactNode } from "react";

import type { Module } from "../api/types";
import { ModuleBadge } from "./badges";

export function Panel({ title, badge, actions, children, className = "" }: {
  title: ReactNode; badge?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <header className="panel-head">
        <h2>{title}</h2>
        {badge}
        <div className="panel-actions">{actions}</div>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function CollapseButton({ collapsed, onToggle, title }: { collapsed: boolean; onToggle: () => void; title: string }) {
  return (
    <button className="collapse-btn" onClick={onToggle} aria-expanded={!collapsed}
            aria-label={`${collapsed ? "Expand" : "Collapse"} ${title}`}>
      {collapsed ? "▸" : "▾"}
    </button>
  );
}

/**
 * A module without a real data source. It explains what is missing and shows no
 * placeholder numbers, charts, alerts or trading results. When `onToggle` is given it
 * can collapse to a one-line bar.
 */
export function UnavailablePanel({ title, module, reason, collapsed = false, onToggle, children }: {
  title: string; module?: Module | undefined; reason?: string; collapsed?: boolean; onToggle?: () => void;
  children?: ReactNode;
}) {
  const why = reason ?? module?.detail ?? "No data source is connected for this module.";
  const badge = <ModuleBadge status={module?.status ?? "UNAVAILABLE"} />;
  const toggle = onToggle && <CollapseButton collapsed={collapsed} onToggle={onToggle} title={title} />;
  if (collapsed) {
    return (
      <section className="panel panel-unavailable panel-collapsed">
        <header className="panel-head">
          {toggle}
          <h2>{title}</h2>
          {badge}
          <span className="collapsed-reason muted small" title={why}>{why}</span>
        </header>
      </section>
    );
  }
  return (
    <Panel title={title} badge={badge} actions={toggle} className="panel-unavailable">
      {children ?? (
        <div className="unavailable">
          <div className="unavailable-icon" aria-hidden>⊘</div>
          <p className="unavailable-title">Not available</p>
          <p>{why}</p>
          {module && <p className="muted small">Data source: {module.data_source}</p>}
        </div>
      )}
    </Panel>
  );
}
