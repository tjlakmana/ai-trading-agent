import type { Row, SortKey } from "../../api/types";
import { ClassBadge, OriginTag, type Origin } from "../../components/badges";
import { fmtPct, fmtPrice, fmtRatio, fmtShares } from "../../lib/format";

interface Column {
  key: string;
  label: string;
  origin?: Origin;
  sort?: SortKey;
  render: (r: Row) => string;
  numeric?: boolean;
}

export const COLUMNS: Column[] = [
  { key: "price", label: "Price", origin: "raw", sort: "price", numeric: true, render: (r) => fmtPrice(r.market.price) },
  { key: "pct", label: "% Chg", origin: "calc", sort: "pct_change", numeric: true,
    render: (r) => fmtPct(r.calculated.pct_change) },
  { key: "gap", label: "Gap", origin: "calc", sort: "gap_pct", numeric: true, render: (r) => fmtPct(r.calculated.gap_pct) },
  { key: "vol", label: "Volume", origin: "raw", sort: "cumulative_volume", numeric: true,
    render: (r) => fmtShares(r.market.cumulative_volume) },
  { key: "ratio", label: "Vol/Avg", origin: "calc", sort: "volume_vs_avg_daily", numeric: true,
    render: (r) => fmtRatio(r.calculated.volume_vs_avg_daily) },
  { key: "float", label: "Float", origin: "raw", sort: "float_shares", numeric: true,
    render: (r) => fmtShares(r.market.float_shares) },
  { key: "hod", label: "Below day high", origin: "calc", sort: "pct_below_day_high", numeric: true,
    render: (r) => fmtPct(r.calculated.pct_below_day_high, 1, false) },
  { key: "rvol", label: "Rel Vol", origin: "vendor", sort: "vendor_relative_volume", numeric: true,
    render: (r) => fmtRatio(r.vendor.relative_volume) },
];

export function RowsTable({ rows, sort, order, onSort, selected, onSelect, showReasons = true }: {
  rows: Row[];
  sort: SortKey;
  order: "asc" | "desc";
  onSort: (key: SortKey) => void;
  selected?: number | undefined;
  onSelect: (row: Row) => void;
  showReasons?: boolean;
}) {
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            <th className="sticky-col">
              <button className="th-btn" onClick={() => onSort("ticker")}>Ticker{sort === "ticker" ? arrow(order) : ""}</button>
            </th>
            <th>Class</th>
            {COLUMNS.map((c) => (
              <th key={c.key} className={c.numeric ? "num" : ""}>
                <button className="th-btn" onClick={() => c.sort && onSort(c.sort)} title={`Sort by ${c.label}`}>
                  {c.label} {c.origin && <OriginTag origin={c.origin} />}
                  {c.sort === sort ? arrow(order) : ""}
                </button>
              </th>
            ))}
            {showReasons && <th>Why</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row_number} className={r.row_number === selected ? "selected" : ""}
                onClick={() => onSelect(r)} tabIndex={0}
                onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(r); } }}>
              <td className="sticky-col ticker">
                <span className="sym">{r.ticker ?? "?"}</span>
                {r.news.title && <span className="news-dot" title={`Finviz headline: ${r.news.title}`}>●</span>}
              </td>
              <td><ClassBadge status={r.status} /></td>
              {COLUMNS.map((c) => <td key={c.key} className={c.numeric ? "num" : ""}>{c.render(r)}</td>)}
              {showReasons && <td className="why">{whyText(r)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const arrow = (order: "asc" | "desc") => (order === "desc" ? " ▾" : " ▴");

export function whyText(r: Row): string {
  if (r.status === "QUALIFIED") return r.warnings_count ? `All HARD checks pass · ${r.warnings_count} warning(s)` : "All HARD checks pass";
  return r.reasons[0] ? r.reasons.join("; ") : r.failed_hard_checks.join(", ");
}
