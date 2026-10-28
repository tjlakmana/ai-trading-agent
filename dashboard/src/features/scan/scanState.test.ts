import { describe, expect, it } from "vitest";

import type { ScanJob, ScanStatus } from "../../api/types";
import { buttonModel, initialScanState, isActive, scanReducer, type ScanUiState } from "./scanState";

// Test-only job objects (shape of the backend's ScanJobOut); not market data.
const job = (over: Partial<ScanJob> = {}): ScanJob => ({
  job_id: "job-1", profile: "broad_v1", state: "RUNNING", requested_at: "2026-10-28T18:00:00Z",
  finished_at: null, run_id: null, error: null, counts: null, ...over,
});
const status = (over: Partial<ScanStatus> = {}): ScanStatus => ({
  running: null, latest: null, cooldown_seconds: 30, cooldown_remaining_seconds: 0,
  finviz_key_configured: true, ...over,
});
const T = Date.parse("2026-10-28T18:00:10Z");

describe("scanReducer", () => {
  it("goes idle -> starting -> running -> succeeded", () => {
    let s: ScanUiState = scanReducer(initialScanState, { type: "start", profile: "broad_v1" });
    expect(s).toEqual({ phase: "starting", profile: "broad_v1" });
    s = scanReducer(s, { type: "started", job: job() });
    expect(s.phase).toBe("running");
    const done = job({ state: "SUCCEEDED", run_id: "r1", finished_at: "2026-10-28T18:00:05Z",
                       counts: { rows: 10, qualified: 6, near_miss: 3, filtered_out: 1, rejected: 0 } });
    s = scanReducer(s, { type: "job", job: done });
    expect(s).toEqual({ phase: "succeeded", job: done });
  });

  it("ignores a second start while starting or running (no duplicate requests)", () => {
    const starting: ScanUiState = { phase: "starting", profile: "broad_v1" };
    expect(scanReducer(starting, { type: "start", profile: "strict_v1" })).toBe(starting);
    const running: ScanUiState = { phase: "running", job: job(), attached: false };
    expect(scanReducer(running, { type: "start", profile: "strict_v1" })).toBe(running);
    expect(isActive(running) && isActive(starting)).toBe(true);
  });

  it("attaches to the scan already running on 409", () => {
    const s = scanReducer({ phase: "starting", profile: "strict_v1" }, { type: "busy", job: job({ job_id: "other" }) });
    expect(s).toEqual({ phase: "running", job: job({ job_id: "other" }), attached: true });
  });

  it("reports failed jobs with the backend's error", () => {
    const failed = job({ state: "FAILED", error: { type: "FinvizAuthError", message: "HTTP 401" } });
    const s = scanReducer({ phase: "running", job: job(), attached: false }, { type: "job", job: failed });
    expect(s).toMatchObject({ phase: "failed", message: "FinvizAuthError: HTTP 401" });
  });

  it("ignores polls for a different job", () => {
    const running: ScanUiState = { phase: "running", job: job(), attached: false };
    expect(scanReducer(running, { type: "job", job: job({ job_id: "stale", state: "SUCCEEDED" }) })).toBe(running);
  });

  it("enters and leaves cooldown", () => {
    let s = scanReducer(initialScanState, { type: "cooldown", retryAfterSeconds: 20, nowMs: T, message: "wait" });
    expect(s).toEqual({ phase: "cooldown", untilMs: T + 20_000, message: "wait" });
    s = scanReducer(s, { type: "tick", nowMs: T + 19_000 });
    expect(s.phase).toBe("cooldown");
    expect(scanReducer(s, { type: "tick", nowMs: T + 20_000 })).toEqual({ phase: "idle" });
  });

  it("surfaces request errors and can be dismissed, but not while running", () => {
    const err = scanReducer({ phase: "starting", profile: "x" }, { type: "error", message: "HTTP 400" });
    expect(err).toEqual({ phase: "failed", message: "HTTP 400" });
    expect(scanReducer(err, { type: "dismiss" })).toEqual({ phase: "idle" });
    const running: ScanUiState = { phase: "running", job: job(), attached: false };
    expect(scanReducer(running, { type: "dismiss" })).toBe(running);
  });
});

describe("buttonModel", () => {
  it("is ready when idle", () => {
    expect(buttonModel(initialScanState, status(), T)).toMatchObject({ label: "Run scan now", disabled: false, tone: "ready" });
  });
  it("is disabled without a Finviz key", () => {
    const m = buttonModel(initialScanState, status({ finviz_key_configured: false }), T);
    expect(m.disabled).toBe(true);
    expect(m.message).toContain("FINVIZ_API_KEY");
  });
  it("shows elapsed time while scanning and disables the button", () => {
    const m = buttonModel({ phase: "running", job: job(), attached: false }, status(), T);
    expect(m).toMatchObject({ label: "Scanning… 10s", disabled: true, tone: "busy" });
  });
  it("tells the user when it is showing a scan someone else started", () => {
    expect(buttonModel({ phase: "running", job: job(), attached: true }, status(), T).message).toContain("already running");
  });
  it("counts down the cooldown", () => {
    const m = buttonModel({ phase: "cooldown", untilMs: T + 12_400, message: "Scan cooldown" }, status(), T);
    expect(m).toMatchObject({ label: "Cooldown 13s", disabled: true, tone: "wait" });
  });
  it("respects the server-side cooldown after success", () => {
    const done = job({ state: "SUCCEEDED", counts: { rows: 10, qualified: 6, near_miss: 3, filtered_out: 1, rejected: 0 } });
    const m = buttonModel({ phase: "succeeded", job: done }, status({ cooldown_remaining_seconds: 29.2 }), T);
    expect(m).toMatchObject({ label: "Cooldown 30s", disabled: true, tone: "ok" });
    expect(m.message).toBe("Scan recorded: 10 rows · 6 qualified · 3 near-miss");
  });
  it("shows a server-reported running scan even before attaching", () => {
    expect(buttonModel(initialScanState, status({ running: job() }), T)).toMatchObject({ disabled: true, tone: "busy" });
  });
  it("allows retry after an error", () => {
    expect(buttonModel({ phase: "failed", message: "HTTP 401" }, status(), T)).toMatchObject({ disabled: false, tone: "error" });
  });
});
