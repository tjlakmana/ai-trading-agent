import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";

import { useTickerHistory } from "../api/queries";
import { ClassBadge } from "../components/badges";
import { Panel } from "../components/Panel";
import { Empty, ErrorBox, Loading } from "../components/states";
import { fmtEt, fmtPct, fmtPrice, fmtRatio, fmtShares, humanize } from "../lib/format";

const TICKER = /^[A-Za-z][A-Za-z0-9]*([.-][A-Za-z0-9]+)?$/;

/** Every recorded observation of one stock across scan runs. */
export function TickerPage() {
  const { ticker } = useParams();
  const navigate = useNavigate();
  const [input, setInput] = useState(ticker ?? "");
  const symbol = ticker?.toUpperCase();
  const history = useTickerHistory(symbol);
  const valid = TICKER.test(input.trim()) && input.trim().length <= 10;

  return (
    <div className="page">
      <div className="page-head">
        <h1>Ticker history</h1>
        <form className="inline-form" onSubmit={(e) => { e.preventDefault(); if (valid) navigate(`/ticker/${input.trim().toUpperCase()}`); }}>
          <input aria-label="Ticker" placeholder="Ticker, e.g. ULBI" value={input} maxLength={10}
                 onChange={(e) => setInput(e.target.value)} />
          <button className="btn btn-primary" disabled={!valid}>Look up</button>
        </form>
      </div>
      {!symbol ? <Empty>Enter a ticker to see every time our scanner recorded it.</Empty> : (
        <Panel title={`${symbol}: recorded observations`}>
          {history.isPending ? <Loading /> : history.isError ? <ErrorBox error={history.error} /> :
            history.data.observations.length === 0 ? <Empty>{symbol} has not appeared in any recorded scan.</Empty> : (
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr><th>Run started (ET)</th><th>Profile</th><th>Class</th><th className="num">Price</th>
                    <th className="num">% Chg</th><th className="num">Volume</th><th className="num">Vol/Avg</th>
                    <th className="num">Float</th><th>HARD checks not passing</th><th /></tr>
                </thead>
                <tbody>
                  {history.data.observations.map((o) => (
                    <tr key={`${o.run_id}-${o.row_number}`}>
                      <td className="nowrap">{fmtEt(o.started_at)}</td>
                      <td>{o.profile}</td>
                      <td><ClassBadge status={o.status} /></td>
                      <td className="num">{fmtPrice(o.price)}</td>
                      <td className="num">{fmtPct(o.pct_change)}</td>
                      <td className="num">{fmtShares(o.cumulative_volume)}</td>
                      <td className="num">{fmtRatio(o.volume_vs_avg_daily)}</td>
                      <td className="num">{fmtShares(o.float_shares)}</td>
                      <td className="why">{o.failed_hard_checks.map(humanize).join(", ") || "—"}</td>
                      <td><Link to={`/runs/${o.run_id}?row=${o.row_number}`}>details →</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
