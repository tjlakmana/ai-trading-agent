import { afterEach, describe, expect, it, vi } from "vitest";

import { api, ApiError, detailMessage } from "./client";

// Test-only fetch stub: records requests and returns canned HTTP responses.
function stubFetch(status: number, body: unknown, headers: Record<string, string> = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return new Response(body === null ? "" : JSON.stringify(body), { status, headers });
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("api client", () => {
  it("sends GETs without the write header and builds query strings", async () => {
    const calls = stubFetch(200, { run_id: "r", total: 0, offset: 0, limit: 50, counts: {}, items: [] });
    await api.rows("abc123", { status: ["QUALIFIED", "NEAR_MISS"], sort: "gap_pct", limit: 50 });
    expect(calls[0]!.url).toBe("/api/runs/abc123/rows?status=QUALIFIED&status=NEAR_MISS&sort=gap_pct&limit=50");
    expect((calls[0]!.init.headers as Record<string, string>)["X-Dashboard-Request"]).toBeUndefined();
  });

  it("marks state-changing requests with X-Dashboard-Request", async () => {
    const calls = stubFetch(200, { changed: [] });
    await api.replay("abc123", { min_pct_change: 0.2 });
    const h = calls[0]!.init.headers as Record<string, string>;
    expect(calls[0]!.init.method).toBe("POST");
    expect(h["X-Dashboard-Request"]).toBe("1");
    expect(JSON.parse(calls[0]!.init.body as string)).toEqual({ overrides: { min_pct_change: 0.2 } });
  });

  it("encodes path parameters", async () => {
    const calls = stubFetch(200, { ticker: "BRK.B", observations: [] });
    await api.tickerHistory("BRK.B/../x");
    expect(calls[0]!.url).toBe("/api/tickers/BRK.B%2F..%2Fx/history");
  });

  it("raises ApiError with the backend's detail", async () => {
    stubFetch(404, { detail: "No scans recorded yet. Run a scan first." });
    await expect(api.latestRun()).rejects.toMatchObject({ status: 404, message: "No scans recorded yet. Run a scan first." });
    await expect(api.latestRun()).rejects.toBeInstanceOf(ApiError);
  });

  it("joins validation error messages", () => {
    expect(detailMessage({ detail: [{ msg: "bad a" }, { msg: "bad b" }] }, "x")).toBe("bad a; bad b");
    expect(detailMessage("plain text", "fallback")).toBe("fallback");
  });
});

describe("startScan", () => {
  const job = { job_id: "j", profile: "broad_v1", state: "RUNNING", requested_at: "2026-10-28T18:00:00Z",
                finished_at: null, run_id: null, error: null, counts: null };

  it("returns the started job on 202", async () => {
    stubFetch(202, job);
    expect(await api.startScan("broad_v1")).toEqual({ kind: "started", job });
  });
  it("returns the running job on 409 (duplicate protection)", async () => {
    stubFetch(409, { detail: "A scan is already running.", job });
    expect(await api.startScan("broad_v1")).toEqual({ kind: "busy", job, message: "A scan is already running." });
  });
  it("returns the cooldown on 429", async () => {
    stubFetch(429, { detail: "Scan cooldown: try again in 20s.", retry_after_seconds: 20 }, { "Retry-After": "20" });
    expect(await api.startScan("broad_v1")).toEqual({ kind: "cooldown", retryAfterSeconds: 20,
                                                      message: "Scan cooldown: try again in 20s." });
  });
  it("throws on other errors", async () => {
    stubFetch(400, { detail: "unknown profile 'x'" });
    await expect(api.startScan("x")).rejects.toMatchObject({ status: 400 });
  });
});
