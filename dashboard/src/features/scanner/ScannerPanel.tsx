import { useState } from "react";
import { Link } from "react-router";

import { useRows } from "../../api/queries";
import type { Row, RowStatus, Run, SortKey } from "../../api/types";
import { OriginLegend } from "../../components/badges";
import { Freshness } from "../../components/Freshness";
import { Empty, ErrorBox, Loading } from "../../components/states";
import { useNow } from "../../lib/useNow";
import { RowsTable } from "./RowsTable";

export type ScannerTab = "gappers" | RowStatus;

interface TabDef {
  id: ScannerTab;
  label: string;
  statuses?: RowStatus[];
  sort: SortKey;
  hint: string;
}

export const TABS: TabDef[] = [
  { id: "gappers", label: "Top Gappers", statuses: ["QUALIFIED", "NEAR_MISS", "FILTERED_OUT"], sort: "gap_pct",
    hint: "Ranked by our gap % (regular-session open vs previous close). Premarket gaps are not available from Finviz." },
  { id: "QUALIFIED", label: "Qualified", statuses: ["QUALIFIED"], sort: "pct_change",
    hint: "Every HARD in-play check passed. Proceed to the next strategy stage - NOT a trade signal." },
  { id: "NEAR_MISS", label: "Near-miss", statuses: ["NEAR_MISS"], sort: "pct_change",
    hint: "Exactly one HARD check did not pass (failed or data unknown). Not a trade signal." },
  { id: "FILTERED_OUT", label: "Filtered out", statuses: ["FILTERED_OUT"], sort: "pct_change",
    hint: "Two or more HARD checks did not pass, or the data was invalid." },
  { id: "REJECTED", label: "Rejected", statuses: ["REJECTED"], sort: "row_number",
    hint: "Rows Finviz returned that could not be normalized (missing or malformed required data)." },
];

const PAGE = 50;

/** Classified rows of one recorded run, with tabs, sorting and paging. */
export function ScannerPanelBody({ run, selected, onSelect, initialTab = "QUALIFIED" }: {
  run: Run; selected?: number | undefined; onSelect: (row: Row) => void; initialTab?: ScannerTab;
}) {
  const [tab, setTab] = useState<ScannerTab>(initialTab);
  const def = TABS.find((t) => t.id === tab)!;
  const [sortState, setSortState] = useState<{ tab: ScannerTab; sort: SortKey; order: "asc" | "desc" }>();
  const sort = sortState?.tab === tab ? sortState.sort : def.sort;
  const order = sortState?.tab === tab ? sortState.order : "desc";
  const [page, setPage] = useState(0);
  const now = useNow(1000);

  const rows = useRows(run.run_id, { status: def.statuses, sort, order, limit: PAGE, offset: page * PAGE });
  const counts = run.counts;
  const tabCount = (t: TabDef) => t.id === "gappers" ? counts.qualified + counts.near_miss + counts.filtered_out
    : t.id === "QUALIFIED" ? counts.qualified : t.id === "NEAR_MISS" ? counts.near_miss
    : t.id === "FILTERED_OUT" ? counts.filtered_out : counts.rejected;

  const onSort = (key: SortKey) => {
    setPage(0);
    setSortState({ tab, sort: key, order: key === sort && order === "desc" ? "asc" : "desc" });
  };

  return (
    <div className="scanner">
      <div className="scanner-meta">
        <span className="run-id">
          Run <Link to={`/runs/${run.run_id}`}>{run.short_id}</Link> · {run.profile} · {run.session ?? "—"} session
        </span>
        <Freshness freshness={run.freshness} nowMs={now} compact />
      </div>
      <div className="tabs" role="tablist">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={t.id === tab} className={`tab tab-${t.id.toLowerCase()}`}
                  onClick={() => { setTab(t.id); setPage(0); }}>
            {t.label} <span className="count">{tabCount(t)}</span>
          </button>
        ))}
      </div>
      <p className="hint">{def.hint}</p>
      {rows.isPending ? <Loading /> : rows.isError ? <ErrorBox error={rows.error} /> : rows.data.total === 0 ? (
        <Empty>No stocks in this class for this run.</Empty>
      ) : (
        <>
          <RowsTable rows={rows.data.items} sort={sort} order={order} onSort={onSort} selected={selected}
                     onSelect={onSelect} />
          {rows.data.total > PAGE && (
            <div className="pager">
              <button className="btn btn-ghost" disabled={page === 0} onClick={() => setPage(page - 1)}>‹ Prev</button>
              <span className="muted">
                {page * PAGE + 1}–{Math.min((page + 1) * PAGE, rows.data.total)} of {rows.data.total}
              </span>
              <button className="btn btn-ghost" disabled={(page + 1) * PAGE >= rows.data.total}
                      onClick={() => setPage(page + 1)}>Next ›</button>
            </div>
          )}
        </>
      )}
      <OriginLegend />
    </div>
  );
}
