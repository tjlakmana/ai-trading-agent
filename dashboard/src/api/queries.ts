// TanStack Query hooks. Every hook reads real backend data; nothing is synthesized client-side.
import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api, ApiError, type RowsQuery } from "./client";

const retryUnlessClientError = (count: number, error: unknown) =>
  !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2;

export const keys = {
  all: ["api"] as const,
  runs: ["api", "runs"] as const,
};

export const useHealth = () =>
  useQuery({ queryKey: ["api", "health"], queryFn: api.health, refetchInterval: 15_000 });

export const useModules = () =>
  useQuery({ queryKey: ["api", "modules"], queryFn: api.modules, refetchInterval: 60_000 });

export const useProfiles = () =>
  useQuery({ queryKey: ["api", "profiles"], queryFn: api.profiles, staleTime: Infinity });

export const useConfigFields = () =>
  useQuery({ queryKey: ["api", "config-fields"], queryFn: api.configFields, staleTime: Infinity });

export const useRuns = (p: { limit?: number; profile?: string; status?: "OK" | "ERROR" } = {}) =>
  useQuery({ queryKey: ["api", "runs", "list", p], queryFn: () => api.runs(p) });

export const useLatestRun = (profile?: string) =>
  useQuery({ queryKey: ["api", "runs", "latest", profile ?? null], queryFn: () => api.latestRun(profile),
             retry: retryUnlessClientError });

export const useRun = (runId: string | undefined) =>
  useQuery({ queryKey: ["api", "runs", "one", runId], queryFn: () => api.run(runId!), enabled: !!runId,
             retry: retryUnlessClientError, staleTime: Infinity });

export const useRows = (runId: string | undefined, p: RowsQuery) =>
  useQuery({ queryKey: ["api", "runs", "rows", runId, p], queryFn: () => api.rows(runId!, p), enabled: !!runId,
             placeholderData: keepPreviousData, retry: retryUnlessClientError, staleTime: Infinity });

export const useRowDetail = (runId: string | undefined, rowNumber: number | undefined) =>
  useQuery({ queryKey: ["api", "runs", "row", runId, rowNumber], queryFn: () => api.row(runId!, rowNumber!),
             enabled: !!runId && rowNumber !== undefined, retry: retryUnlessClientError, staleTime: Infinity });

export const useTickerHistory = (ticker: string | undefined) =>
  useQuery({ queryKey: ["api", "runs", "ticker", ticker], queryFn: () => api.tickerHistory(ticker!),
             enabled: !!ticker, retry: retryUnlessClientError });

export const useScanStatus = (fast: boolean) =>
  useQuery({ queryKey: ["api", "scan-status"], queryFn: api.scanStatus, refetchInterval: fast ? 1_000 : 10_000 });
