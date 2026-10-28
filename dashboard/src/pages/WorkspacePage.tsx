import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router";

import { ApiError } from "../api/client";
import { useLatestRun, useModules, useProfiles } from "../api/queries";
import type { Module } from "../api/types";
import { ModuleBadge } from "../components/badges";
import { ChartSlot } from "../components/ChartSlot";
import { Panel, UnavailablePanel } from "../components/Panel";
import { ErrorBox } from "../components/states";
import { StockDrawer } from "../features/scanner/StockDrawer";
import { useCollapsed } from "../lib/collapse";
import {
  resolvePanel, WORKSPACE_LAYOUT, type ModuleId, type Selection, type WorkspaceContext,
} from "../modules/registry";
import { WORKSPACE_MODULES } from "../modules/workspaceModules";

/** The trading workspace: every module, live where real data exists, labelled where it does not. */
export function WorkspacePage() {
  const profiles = useProfiles();
  const [profile, setProfile] = useState("broad_v1");
  const latest = useLatestRun(profile);
  const modules = useModules();
  const [selection, setSelection] = useState<Selection>();
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Sidebar module links (/#module-id) scroll to their panel.
  const { hash } = useLocation();
  useEffect(() => {
    if (hash.startsWith("#module-")) document.getElementById(hash.slice(1))?.scrollIntoView({ behavior: "smooth" });
  }, [hash, modules.data]);

  const noRun = latest.isError && latest.error instanceof ApiError && latest.error.status === 404;
  const select = useCallback((s: Selection) => { setSelection(s); setDrawerOpen(true); }, []);
  const closeDrawer = useCallback(() => setDrawerOpen(false), []);
  const ctx: WorkspaceContext = { run: noRun ? undefined : latest.data, selection, select };

  return (
    <div className={`page ${drawerOpen && selection ? "with-drawer" : ""}`}>
      <div className="page-head">
        <h1>Workspace</h1>
        <div className="segmented" role="tablist" aria-label="Discovery profile">
          {(profiles.data ?? []).map((p) => (
            <button key={p.name} role="tab" aria-selected={p.name === profile} className={p.name === profile ? "on" : ""}
                    onClick={() => { setProfile(p.name); setSelection(undefined); setDrawerOpen(false); }}
                    title={p.filters.map((f) => `${f.code}: ${f.meaning}`).join("\n")}>
              {p.name}
            </button>
          ))}
        </div>
        <span className="muted small">Latest successful scan for this profile · click a stock for details</span>
      </div>
      {modules.isError && <ErrorBox error={modules.error} title="Could not load module status" />}
      {latest.isError && !noRun && <ErrorBox error={latest.error} />}
      <div className="workspace-grid">
        {WORKSPACE_LAYOUT.map((id) => (
          <WorkspaceCell key={id} id={id} status={modules.data?.find((m) => m.id === id)} ctx={ctx} />
        ))}
      </div>
      <StockDrawer runId={drawerOpen ? selection?.runId : undefined} rowNumber={drawerOpen ? selection?.rowNumber : undefined}
                   onClose={closeDrawer} />
    </div>
  );
}

function WorkspaceCell({ id, status, ctx }: { id: ModuleId; status: Module | undefined; ctx: WorkspaceContext }) {
  const def = WORKSPACE_MODULES[id]!;
  const res = resolvePanel(def, status);
  const [collapsed, toggle] = useCollapsed(id, res.kind === "unavailable" && def.collapsedWhenUnavailable);
  const isCollapsed = res.kind === "unavailable" && collapsed;
  return (
    <div className={`ws-cell span-${def.span} ${isCollapsed ? "is-collapsed" : ""} ${def.chartSlot ? "ws-chart" : ""}`}
         id={`module-${id}`}>
      {res.kind === "component" ? (
        <Panel title={def.title} badge={status && <ModuleBadge status={status.status} />}>
          <res.component ctx={ctx} />
        </Panel>
      ) : (
        <UnavailablePanel title={def.title} module={status} reason={res.reason} collapsed={collapsed} onToggle={toggle}>
          {def.chartSlot ? <ChartSlot module={status} reason={res.reason} /> : undefined}
        </UnavailablePanel>
      )}
    </div>
  );
}
