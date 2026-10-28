import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useReducer } from "react";

import { api } from "../../api/client";
import { keys, useScanStatus } from "../../api/queries";
import { initialScanState, isActive, scanReducer } from "./scanState";

/** Drives "Run scan now": starts a scan, polls its job, and refreshes history when it finishes. */
export function useScan() {
  const [state, dispatch] = useReducer(scanReducer, initialScanState);
  const status = useScanStatus(isActive(state) || state.phase === "cooldown");
  const qc = useQueryClient();

  // A scan started elsewhere (another tab, a previous page load): follow it.
  useEffect(() => {
    if (state.phase === "idle" && status.data?.running) dispatch({ type: "busy", job: status.data.running });
  }, [state.phase, status.data?.running]);

  // Poll the job we are tracking.
  const runningId = state.phase === "running" ? state.job.job_id : null;
  useEffect(() => {
    if (!runningId) return;
    let stop = false;
    const id = window.setInterval(async () => {
      try {
        const job = await api.scanJob(runningId);
        if (!stop) dispatch({ type: "job", job });
      } catch (e) {
        if (!stop) dispatch({ type: "error", message: e instanceof Error ? e.message : String(e) });
      }
    }, 1000);
    return () => { stop = true; window.clearInterval(id); };
  }, [runningId]);

  // When a scan finishes (either way), refresh everything that reads history.
  useEffect(() => {
    if (state.phase === "succeeded" || (state.phase === "failed" && state.job)) {
      void qc.invalidateQueries({ queryKey: keys.runs });
      void qc.invalidateQueries({ queryKey: ["api", "modules"] });
      void qc.invalidateQueries({ queryKey: ["api", "health"] });
    }
    void qc.invalidateQueries({ queryKey: ["api", "scan-status"] });
  }, [state.phase, qc]);

  // Cooldown countdown.
  useEffect(() => {
    if (state.phase !== "cooldown") return;
    const id = window.setInterval(() => dispatch({ type: "tick", nowMs: Date.now() }), 500);
    return () => window.clearInterval(id);
  }, [state.phase]);

  const start = useCallback(async (profile: string) => {
    if (isActive(state)) return; // never send a duplicate request
    dispatch({ type: "start", profile });
    try {
      const result = await api.startScan(profile);
      if (result.kind === "started") dispatch({ type: "started", job: result.job });
      else if (result.kind === "busy") dispatch({ type: "busy", job: result.job });
      else dispatch({ type: "cooldown", retryAfterSeconds: result.retryAfterSeconds, nowMs: Date.now(),
                      message: result.message });
    } catch (e) {
      dispatch({ type: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }, [state]);

  return { state, status: status.data, start, dismiss: () => dispatch({ type: "dismiss" }) };
}
