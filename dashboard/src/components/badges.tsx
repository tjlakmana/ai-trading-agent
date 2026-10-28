import type { ModuleStatus, RowStatus } from "../api/types";

const CLASS_LABEL: Record<RowStatus, string> = {
  QUALIFIED: "Qualified",
  NEAR_MISS: "Near-miss",
  FILTERED_OUT: "Filtered out",
  REJECTED: "Rejected",
};

export const classLabel = (s: RowStatus) => CLASS_LABEL[s];

export function ClassBadge({ status }: { status: RowStatus }) {
  return <span className={`badge cls-${status.toLowerCase()}`}>{CLASS_LABEL[status]}</span>;
}

export function ModuleBadge({ status }: { status: ModuleStatus }) {
  const label = status === "AVAILABLE" ? "Live data" : status === "PARTIAL" ? "Partial" : "Unavailable";
  return <span className={`badge mod-${status.toLowerCase()}`}>{label}</span>;
}

export type Origin = "raw" | "calc" | "vendor";

const ORIGIN: Record<Origin, { tag: string; title: string }> = {
  raw: { tag: "RAW", title: "Raw Finviz market data (units converted). Not calculated by us." },
  calc: { tag: "OURS", title: "Calculated by our deterministic code from raw data." },
  vendor: { tag: "FV", title: "Finviz-calculated value. Discovery only - never used in our checks." },
};

export function OriginTag({ origin }: { origin: Origin }) {
  return (
    <span className={`origin origin-${origin}`} title={ORIGIN[origin].title}>
      {ORIGIN[origin].tag}
    </span>
  );
}

export function OriginLegend() {
  return (
    <div className="legend" aria-label="Value origin legend">
      {(Object.keys(ORIGIN) as Origin[]).map((o) => (
        <span key={o} className="legend-item">
          <OriginTag origin={o} /> {ORIGIN[o].title.split(".")[0]}
        </span>
      ))}
    </div>
  );
}

export function LevelBadge({ level }: { level: string }) {
  return <span className={`badge lvl-${level.toLowerCase()}`}>{level}</span>;
}

export function CheckStatusBadge({ status }: { status: "PASS" | "FAIL" | "UNKNOWN" }) {
  return <span className={`badge chk-${status.toLowerCase()}`}>{status}</span>;
}
