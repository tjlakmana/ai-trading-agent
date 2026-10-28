import { describe, expect, it } from "vitest";

import type { Module } from "../api/types";
import { resolvePanel, WORKSPACE_LAYOUT, WORKSPACE_ORDER } from "./registry";
import { WORKSPACE_MODULES } from "./workspaceModules";

const mod = (id: string, status: Module["status"]): Module =>
  ({ id, title: id, status, data_source: "src", detail: `${id} detail` });

describe("workspace registry", () => {
  it("follows the Ross Cameron-inspired workflow order with all eight modules", () => {
    expect(WORKSPACE_ORDER).toEqual(["scanner", "hod_alerts", "stock", "charts", "news", "ai_agent", "paper", "level2"]);
    for (const id of WORKSPACE_ORDER) expect(WORKSPACE_MODULES[id]?.id).toBe(id);
  });

  it("places the full-width scanner first and gives the chart slot a large cell", () => {
    expect([...WORKSPACE_LAYOUT].sort()).toEqual([...WORKSPACE_ORDER].sort());
    expect(WORKSPACE_LAYOUT[0]).toBe("scanner");
    expect(WORKSPACE_MODULES.scanner!.span).toBe(12);
    expect(WORKSPACE_LAYOUT[1]).toBe("charts");
    expect(WORKSPACE_MODULES.charts!.span).toBe(8);
    expect(WORKSPACE_MODULES.charts!.chartSlot).toBe(true);
  });

  it("collapses small unavailable modules by default, but not the chart slot", () => {
    for (const id of ["hod_alerts", "ai_agent", "paper", "level2"] as const) {
      expect(WORKSPACE_MODULES[id]!.collapsedWhenUnavailable).toBe(true);
    }
    expect(WORKSPACE_MODULES.charts!.collapsedWhenUnavailable).toBe(false);
    expect(WORKSPACE_MODULES.scanner!.collapsedWhenUnavailable).toBe(false);
  });

  it("only modules backed by real recorded data have components", () => {
    const built = WORKSPACE_ORDER.filter((id) => WORKSPACE_MODULES[id]!.component);
    expect(built).toEqual(["scanner", "stock", "news"]);
  });

  it("renders a component only when the backend reports a data source", () => {
    expect(resolvePanel(WORKSPACE_MODULES.scanner!, mod("scanner", "AVAILABLE")).kind).toBe("component");
    expect(resolvePanel(WORKSPACE_MODULES.news!, mod("news", "PARTIAL")).kind).toBe("component");
    expect(resolvePanel(WORKSPACE_MODULES.scanner!, mod("scanner", "UNAVAILABLE")))
      .toEqual({ kind: "unavailable", reason: "scanner detail" });
  });

  it("fails closed when the backend status is missing", () => {
    expect(resolvePanel(WORKSPACE_MODULES.scanner!, undefined).kind).toBe("unavailable");
  });

  it("never fakes a future module, even if the backend later reports data", () => {
    for (const id of ["hod_alerts", "charts", "ai_agent", "paper", "level2"] as const) {
      const res = resolvePanel(WORKSPACE_MODULES[id]!, mod(id, "AVAILABLE"));
      expect(res.kind).toBe("unavailable");
      expect(res.kind === "unavailable" && res.reason).toContain("not built yet");
    }
  });
});
