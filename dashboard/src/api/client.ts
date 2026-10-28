// Thin, typed client for the loopback-only dashboard API (proxied at /api by Vite).
// State-changing requests carry X-Dashboard-Request, which the backend requires.
import type {
  ConfigField, Health, Module, OverrideValue, Profile, Replay, RowDetail, RowsPage, RowStatus, Run,
  ScanJob, ScanStatus, SortKey, TickerHistory,
} from "./types";

export class ApiError extends Error {
  constructor(readonly status: number, message: string, readonly body: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export function detailMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail.map((d) => (d && typeof d === "object" && "msg" in d ? String(d.msg) : String(d))).join("; ");
    }
  }
  return fallback;
}

async function send(path: string, init: RequestInit = {}): Promise<{ status: number; body: unknown; headers: Headers }> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (init.method && init.method !== "GET") headers["X-Dashboard-Request"] = "1";
  const res = await fetch(path, { ...init, headers: { ...headers, ...(init.headers as Record<string, string>) } });
  const text = await res.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = text;
    }
  }
  return { status: res.status, body, headers: res.headers };
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const { status, body } = await send(path, init);
  if (status < 200 || status >= 300) throw new ApiError(status, detailMessage(body, `HTTP ${status}`), body);
  return body as T;
}

function query(params: Record<string, string | number | readonly string[] | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue;
    if (Array.isArray(value)) value.forEach((v) => q.append(key, v));
    else q.set(key, String(value));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}

const enc = encodeURIComponent;

export interface RowsQuery {
  status?: readonly RowStatus[];
  ticker?: string;
  sort?: SortKey;
  order?: "asc" | "desc";
  limit?: number;
  offset?: number;
}

export type StartScanResult =
  | { kind: "started"; job: ScanJob }
  | { kind: "busy"; job: ScanJob; message: string }
  | { kind: "cooldown"; retryAfterSeconds: number; message: string };

export const api = {
  health: () => request<Health>("/api/health"),
  modules: () => request<Module[]>("/api/modules"),
  profiles: () => request<Profile[]>("/api/profiles"),
  configFields: () => request<ConfigField[]>("/api/in-play-config"),
  runs: (p: { limit?: number; profile?: string; status?: "OK" | "ERROR" } = {}) =>
    request<Run[]>(`/api/runs${query(p)}`),
  latestRun: (profile?: string) => request<Run>(`/api/runs/latest${query({ profile })}`),
  run: (runId: string) => request<Run>(`/api/runs/${enc(runId)}`),
  rows: (runId: string, p: RowsQuery = {}) => request<RowsPage>(`/api/runs/${enc(runId)}/rows${query({ ...p })}`),
  row: (runId: string, rowNumber: number) => request<RowDetail>(`/api/runs/${enc(runId)}/rows/${rowNumber}`),
  tickerHistory: (ticker: string) => request<TickerHistory>(`/api/tickers/${enc(ticker)}/history`),
  replay: (runId: string, overrides: Record<string, OverrideValue>) =>
    request<Replay>(`/api/runs/${enc(runId)}/replay`, { method: "POST", body: JSON.stringify({ overrides }) }),
  scanStatus: () => request<ScanStatus>("/api/scans/status"),
  scanJob: (jobId: string) => request<ScanJob>(`/api/scans/${enc(jobId)}`),
  async startScan(profile: string): Promise<StartScanResult> {
    const { status, body, headers } = await send("/api/scans", { method: "POST", body: JSON.stringify({ profile }) });
    if (status === 202) return { kind: "started", job: body as ScanJob };
    if (status === 409 && body && typeof body === "object" && "job" in body) {
      return { kind: "busy", job: (body as { job: ScanJob }).job, message: detailMessage(body, "A scan is running") };
    }
    if (status === 429) {
      const fromBody = (body as { retry_after_seconds?: number } | null)?.retry_after_seconds;
      const retry = Number(fromBody ?? headers.get("Retry-After") ?? 30);
      return { kind: "cooldown", retryAfterSeconds: Number.isFinite(retry) ? retry : 30,
               message: detailMessage(body, "Scan cooldown") };
    }
    throw new ApiError(status, detailMessage(body, `HTTP ${status}`), body);
  },
};
