import { Link } from "react-router";

import { useRowDetail } from "../../api/queries";
import type { Check, RowDetail as RowDetailData } from "../../api/types";
import { CheckStatusBadge, ClassBadge, LevelBadge, OriginTag } from "../../components/badges";
import { Freshness } from "../../components/Freshness";
import { Empty, ErrorBox, Loading } from "../../components/states";
import { fmtCheckValue, fmtInt, fmtPct, fmtPrice, fmtRatio, fmtShares, humanize } from "../../lib/format";
import { useNow } from "../../lib/useNow";

/** Why a stock passed or failed: every check, grouped values by origin, the vendor headline, raw cells. */
export function RowDetail({ runId, rowNumber }: { runId: string | undefined; rowNumber: number | undefined }) {
  const detail = useRowDetail(runId, rowNumber);
  const now = useNow(1000);
  if (!runId || rowNumber === undefined) return <Empty>Select a stock to see why it passed or failed.</Empty>;
  if (detail.isPending) return <Loading />;
  if (detail.isError) return <ErrorBox error={detail.error} />;
  const d = detail.data;
  return (
    <div className="detail">
      <div className="detail-head">
        <div>
          <span className="detail-sym">{d.ticker ?? "?"}</span> <ClassBadge status={d.status} />
          <div className="muted small">{[d.company, d.exchange].filter(Boolean).join(" · ") || "—"}</div>
        </div>
        {d.ticker && <Link className="btn btn-ghost" to={`/ticker/${d.ticker}`}>Ticker history →</Link>}
      </div>
      <Freshness freshness={d.freshness} nowMs={now} />
      <Verdict d={d} />
      {d.hard_checks.length > 0 && <Checks title="HARD checks (decide qualification)" checks={d.hard_checks} />}
      {d.quality_checks.length > 0 && <Checks title="PREFERRED checks (warnings only)" checks={d.quality_checks} />}
      {d.normalization_errors.length > 0 && (
        <div className="callout callout-error">
          <strong>Row could not be normalized</strong>
          <ul>{d.normalization_errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      <ValueGroups d={d} />
      <div className="news-box">
        <div className="group-title">Latest headline <OriginTag origin="vendor" /></div>
        {d.news.title ? (
          <p>{d.news.title} <span className="muted small">({d.news.time ?? "time unknown"} · not classified, catalyst unknown)</span></p>
        ) : <p className="muted">No Finviz headline in this row.</p>}
      </div>
      {d.warnings.length > 0 && (
        <div className="callout callout-warn">
          <strong>Warnings</strong>
          <ul>{d.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      <details className="raw">
        <summary>Raw Finviz cells ({Object.keys(d.raw).length}) - unchanged, as received</summary>
        <dl>{Object.entries(d.raw).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v || "''"}</dd></div>)}</dl>
      </details>
    </div>
  );
}

function Verdict({ d }: { d: RowDetailData }) {
  const text = {
    QUALIFIED: "Every HARD check passed. This only means \"proceed to the next strategy stage\" - not a trade signal.",
    NEAR_MISS: `Exactly one HARD check did not pass: ${d.failed_hard_checks.map(humanize).join(", ")}.`,
    FILTERED_OUT: d.valid_data === false ? "The snapshot data was invalid." :
      `${d.hard_failures} HARD checks did not pass: ${d.failed_hard_checks.map(humanize).join(", ")}.`,
    REJECTED: "Finviz returned this row, but required data was missing or malformed.",
  }[d.status];
  return <p className={`verdict verdict-${d.status.toLowerCase()}`}>{text}</p>;
}

function Checks({ title, checks }: { title: string; checks: Check[] }) {
  return (
    <div className="checks">
      <div className="group-title">{title} <OriginTag origin="calc" /></div>
      <table className="data-table compact">
        <thead><tr><th>Check</th><th>Level</th><th>Result</th><th className="num">Actual</th><th className="num">Threshold</th><th>Explanation</th></tr></thead>
        <tbody>
          {checks.map((c) => (
            <tr key={c.name} className={`chk-row chk-row-${c.status.toLowerCase()}`}>
              <td>{humanize(c.name)}</td>
              <td><LevelBadge level={c.level} /></td>
              <td><CheckStatusBadge status={c.status} /></td>
              <td className="num">{fmtCheckValue(c.name, c.actual)}</td>
              <td className="num">{fmtCheckValue(c.name, c.threshold)}</td>
              <td className="why">{c.message}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ValueGroups({ d }: { d: RowDetailData }) {
  const m = d.market, c = d.calculated, v = d.vendor;
  return (
    <div className="value-groups">
      <Group title="Market data" origin="raw" note="Raw Finviz inputs, units converted" items={[
        ["Price", fmtPrice(m.price)], ["Prev close", fmtPrice(m.previous_close)], ["Open", fmtPrice(m.open_price)],
        ["Day high", fmtPrice(m.day_high)], ["Day low", fmtPrice(m.day_low)],
        ["Volume", fmtInt(m.cumulative_volume)], ["Avg volume", fmtInt(m.average_daily_volume)],
        ["Float", fmtShares(m.float_shares)], ["Trades", fmtInt(m.trades)],
      ]} />
      <Group title="Calculated" origin="calc" note="Our deterministic metrics" items={[
        ["% change", fmtPct(c.pct_change)], ["Gap", fmtPct(c.gap_pct)],
        ["Vol / avg daily", fmtRatio(c.volume_vs_avg_daily)],
        ["Below day high", fmtPct(c.pct_below_day_high, 1, false)],
        ["Room to resistance", fmtPct(c.room_to_resistance_pct)],
      ]} footnote="Vol/avg daily compares partial-session volume to a full-day average: it is not time-of-day RVOL. 'Below day high' is a snapshot at fetch time, not an alert." />
      <Group title="Finviz-calculated" origin="vendor" note="Discovery only - never used in our checks" items={[
        ["Relative volume", fmtRatio(v.relative_volume)], ["Change", fmtPct(v.change_pct)],
        ["Change from open", fmtPct(v.change_from_open_pct)], ["Gap", fmtPct(v.gap_pct)],
        ["Perf 1m", fmtPct(v.perf_1m_pct)], ["Perf 5m", fmtPct(v.perf_5m_pct)], ["Perf 15m", fmtPct(v.perf_15m_pct)],
        ["Perf 1h", fmtPct(v.perf_1h_pct)],
      ]} />
    </div>
  );
}

function Group({ title, origin, note, items, footnote }: {
  title: string; origin: "raw" | "calc" | "vendor"; note: string; items: [string, string][]; footnote?: string;
}) {
  return (
    <div className={`group group-${origin}`}>
      <div className="group-title">{title} <OriginTag origin={origin} /></div>
      <div className="muted small">{note}</div>
      <dl className="kv">{items.map(([k, val]) => <div key={k}><dt>{k}</dt><dd>{val}</dd></div>)}</dl>
      {footnote && <p className="muted small">{footnote}</p>}
    </div>
  );
}
