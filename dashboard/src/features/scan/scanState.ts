// "Run scan now" UI state machine (pure; unit tested). The backend is the authority:
// it enforces one scan at a time and the cooldown. The UI mirrors that and never
// sends a second request while one is starting or running.
import type { ScanJob, ScanStatus } from "../../api/types";

export type ScanUiState =
  | { phase: "idle" }
  | { phase: "starting"; profile: string }
  | { phase: "running"; job: ScanJob; attached: boolean }
  | { phase: "succeeded"; job: ScanJob }
  | { phase: "failed"; message: string; job?: ScanJob }
  | { phase: "cooldown"; untilMs: number; message: string };

export type ScanEvent =
  | { type: "start"; profile: string }
  | { type: "started"; job: ScanJob }
  | { type: "busy"; job: ScanJob }
  | { type: "job"; job: ScanJob }
  | { type: "cooldown"; retryAfterSeconds: number; nowMs: number; message: string }
  | { type: "error"; message: string }
  | { type: "tick"; nowMs: number }
  | { type: "dismiss" };

export const initialScanState: ScanUiState = { phase: "idle" };

export const isActive = (s: ScanUiState) => s.phase === "starting" || s.phase === "running";

function fromJob(job: ScanJob, attached = false): ScanUiState {
  if (job.state === "RUNNING") return { phase: "running", job, attached };
  if (job.state === "SUCCEEDED") return { phase: "succeeded", job };
  return { phase: "failed", job, message: job.error ? `${job.error.type}: ${job.error.message}` : "Scan failed" };
}

export function scanReducer(state: ScanUiState, event: ScanEvent): ScanUiState {
  switch (event.type) {
    case "start":
      return isActive(state) ? state : { phase: "starting", profile: event.profile };
    case "started":
      return fromJob(event.job);
    case "busy":
      return fromJob(event.job, true);
    case "job":
      // Only follow the job we are tracking; ignore stale polls.
      if (state.phase === "running" && state.job.job_id === event.job.job_id) return fromJob(event.job, state.attached);
      return state;
    case "cooldown":
      return { phase: "cooldown", untilMs: event.nowMs + event.retryAfterSeconds * 1000, message: event.message };
    case "error":
      return { phase: "failed", message: event.message };
    case "tick":
      return state.phase === "cooldown" && event.nowMs >= state.untilMs ? { phase: "idle" } : state;
    case "dismiss":
      return isActive(state) ? state : { phase: "idle" };
  }
}

export interface ButtonModel {
  label: string;
  disabled: boolean;
  tone: "ready" | "busy" | "ok" | "error" | "wait" | "off";
  message: string | null;
}

/** What the button and status line show, combining local state with the server's scan status. */
export function buttonModel(state: ScanUiState, status: ScanStatus | undefined, nowMs: number): ButtonModel {
  if (status && !status.finviz_key_configured) {
    return { label: "Run scan now", disabled: true, tone: "off",
             message: "FINVIZ_API_KEY is not configured in .env" };
  }
  switch (state.phase) {
    case "starting":
      return { label: "Starting…", disabled: true, tone: "busy", message: `Requesting a ${state.profile} scan` };
    case "running": {
      const secs = Math.max(0, Math.round((nowMs - Date.parse(state.job.requested_at)) / 1000));
      return { label: `Scanning… ${secs}s`, disabled: true, tone: "busy",
               message: state.attached ? `Showing the scan already running (${state.job.profile})`
                                       : `Fetching ${state.job.profile} from Finviz`};
    }
    case "cooldown": {
      const secs = Math.max(0, Math.ceil((state.untilMs - nowMs) / 1000));
      return { label: `Cooldown ${secs}s`, disabled: true, tone: "wait", message: state.message };
    }
    case "failed":
      return { label: "Run scan now", disabled: false, tone: "error", message: state.message };
    case "succeeded": {
      const c = state.job.counts;
      const wait = status?.cooldown_remaining_seconds ?? 0;
      return { label: wait > 0 ? `Cooldown ${Math.ceil(wait)}s` : "Run scan now", disabled: wait > 0, tone: "ok",
               message: c ? `Scan recorded: ${c.rows} rows · ${c.qualified} qualified · ${c.near_miss} near-miss`
                          : "Scan recorded" };
    }
    case "idle": {
      if (status?.running) {
        return { label: "Scanning…", disabled: true, tone: "busy", message: "A scan is running" };
      }
      const wait = status?.cooldown_remaining_seconds ?? 0;
      if (wait > 0) return { label: `Cooldown ${Math.ceil(wait)}s`, disabled: true, tone: "wait", message: null };
      return { label: "Run scan now", disabled: false, tone: "ready", message: null };
    }
  }
}
