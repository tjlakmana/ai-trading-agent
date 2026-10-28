// Display formatting. Missing values always render as an em dash, never as 0.
export const DASH = "—";

type Num = number | null | undefined;

export const fmtPct = (v: Num, digits = 1, signed = true): string =>
  v == null ? DASH : `${signed && v > 0 ? "+" : ""}${(v * 100).toFixed(digits)}%`;

export const fmtPrice = (v: Num): string => (v == null ? DASH : `$${v.toFixed(v < 1 ? 4 : 2)}`);

export const fmtRatio = (v: Num): string => (v == null ? DASH : `${v.toFixed(2)}×`);

export const fmtInt = (v: Num): string => (v == null ? DASH : Math.round(v).toLocaleString("en-US"));

export function fmtShares(v: Num): string {
  if (v == null) return DASH;
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return fmtInt(v);
}

const ET = new Intl.DateTimeFormat("en-US", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
  hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", timeZoneName: "short",
});

/** "2026-10-28 14:57:39 EDT" (or "14:57:39 EDT" without the date). */
export function fmtEt(iso: string | null | undefined, withDate = true): string {
  if (!iso) return DASH;
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return DASH;
  const p = Object.fromEntries(ET.formatToParts(new Date(t)).map((x) => [x.type, x.value]));
  const time = `${p.hour}:${p.minute}:${p.second} ${p.timeZoneName}`;
  return withDate ? `${p.year}-${p.month}-${p.day} ${time}` : time;
}

/** Compact age: 45s, 12m, 3h 05m, 2d. */
export function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return DASH;
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
  return `${Math.floor(s / 86400)}d`;
}

export const ageSeconds = (iso: string | null | undefined, nowMs: number): number | null =>
  iso ? (nowMs - Date.parse(iso)) / 1000 : null;

/** Format an in-play check's actual/threshold using the unit implied by the check name. */
export function fmtCheckValue(name: string, v: number | string | null | undefined): string {
  if (v == null) return DASH;
  if (typeof v === "string") return v;
  if (name.includes("pct") || name.includes("room")) return fmtPct(v);
  if (name.includes("price")) return fmtPrice(v);
  if (name.includes("volume_vs_avg")) return fmtRatio(v);
  return fmtInt(v);
}

export const humanize = (id: string): string => id.replace(/_/g, " ");
