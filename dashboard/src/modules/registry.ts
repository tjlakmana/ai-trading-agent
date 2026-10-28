// Workspace module registry, in Ross Cameron-inspired workflow order.
// To add a module later (Alpaca charts, HOD alerts, AI agent, paper trading, Level 2):
// build its component and set `component` here. Availability itself comes from the backend
// (GET /api/modules), so a component never renders without a real data source.
import type { ComponentType } from "react";

import type { Module, Run } from "../api/types";

export type ModuleId = "scanner" | "hod_alerts" | "stock" | "charts" | "news" | "ai_agent" | "paper" | "level2";

export interface Selection {
  runId: string;
  rowNumber: number;
}

export interface WorkspaceContext {
  run: Run | undefined;
  selection: Selection | undefined;
  select: (s: Selection) => void;
}

export interface WorkspaceModuleDef {
  id: ModuleId;
  title: string;
  /** Columns spanned on the 12-column desktop grid. */
  span: 4 | 5 | 6 | 7 | 8 | 12;
  component?: ComponentType<{ ctx: WorkspaceContext }>;
  /** Rendered as the large chart slot while unavailable (no data drawn). */
  chartSlot?: boolean;
  /** Whether the panel starts collapsed while the module is unavailable. */
  collapsedWhenUnavailable: boolean;
}

export type PanelResolution =
  | { kind: "component"; component: ComponentType<{ ctx: WorkspaceContext }> }
  | { kind: "unavailable"; reason: string };

/** Decide whether a module may render live content. Fails closed to a labelled unavailable panel. */
export function resolvePanel(def: WorkspaceModuleDef, status: Module | undefined): PanelResolution {
  if (!status) return { kind: "unavailable", reason: "Module status unknown: the backend did not report it." };
  if (status.status === "UNAVAILABLE") return { kind: "unavailable", reason: status.detail };
  if (!def.component) {
    return { kind: "unavailable", reason: "The backend reports a data source, but this dashboard component is not built yet." };
  }
  return { kind: "component", component: def.component };
}

/** Workflow order (navigation, module status lists). */
export const WORKSPACE_ORDER: readonly ModuleId[] = [
  "scanner", "hod_alerts", "stock", "charts", "news", "ai_agent", "paper", "level2",
];

/**
 * Visual placement on the workspace grid: the full-width scanner first, then the large
 * chart slot beside the watchlist, then the remaining modules.
 */
export const WORKSPACE_LAYOUT: readonly ModuleId[] = [
  "scanner", "charts", "stock", "hod_alerts", "news", "ai_agent", "paper", "level2",
];
