import type { Freshness as FreshnessData } from "../api/types";
import { ageSeconds, fmtAge, fmtEt } from "../lib/format";

/**
 * Shows when we fetched the data, and that the market quote time is unknown.
 * The age is the age of the fetch, never presented as quote age.
 */
export function Freshness({ freshness, nowMs, compact = false }: {
  freshness: FreshnessData; nowMs: number; compact?: boolean;
}) {
  const age = ageSeconds(freshness.fetched_at, nowMs);
  const unknown = freshness.quote_freshness === "UNKNOWN";
  return (
    <div className={`freshness ${compact ? "compact" : ""}`} title={freshness.note}>
      <span className="fresh-fetched">
        <span className="muted">Fetched</span>{" "}
        {freshness.fetched_at ? (
          <>
            <time dateTime={freshness.fetched_at}>{fmtEt(freshness.fetched_at, !compact)}</time>
            <span className="muted"> · {fmtAge(age)} ago</span>
          </>
        ) : (
          <span className="muted">no data received</span>
        )}
      </span>
      <span className={`badge ${unknown ? "fresh-unknown" : "fresh-verified"}`}>
        Quote time: {unknown ? "UNKNOWN" : "verified"}
      </span>
    </div>
  );
}
