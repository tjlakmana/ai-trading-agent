import { useState } from "react";
import { Link, useNavigate } from "react-router";

import { useProfiles, useRuns } from "../api/queries";
import { Panel } from "../components/Panel";
import { Empty, ErrorBox, Loading } from "../components/states";
import { ageSeconds, fmtAge, fmtEt } from "../lib/format";
import { useNow } from "../lib/useNow";

/** Every recorded scan attempt, successes and failures, newest first. */
export function HistoryPage() {
  const [profile, setProfile] = useState("");
  const [status, setStatus] = useState<"" | "OK" | "ERROR">("");
  const profiles = useProfiles();
  const runs = useRuns({ limit: 200, profile: profile || undefined, status: status || undefined });
  const navigate = useNavigate();
  const now = useNow(5000);

  return (
    <div className="page">
      <div className="page-head">
        <h1>Scan history</h1>
        <select aria-label="Filter by profile" value={profile} onChange={(e) => setProfile(e.target.value)}>
          <option value="">All profiles</option>
          {(profiles.data ?? []).map((p) => <option key={p.name}>{p.name}</option>)}
          <option value="custom_tickers">custom_tickers</option>
        </select>
        <select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value as "" | "OK" | "ERROR")}>
          <option value="">All attempts</option>
          <option value="OK">Successful</option>
          <option value="ERROR">Failed</option>
        </select>
      </div>
      <Panel title="Recorded runs" badge={<span className="badge mod-available">Append-only</span>}>
        {runs.isPending ? <Loading /> : runs.isError ? <ErrorBox error={runs.error} /> : runs.data.length === 0 ? (
          <Empty>No scans recorded yet. Use <strong>Run scan now</strong>, or run <code>python -m data.finviz</code>.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Run</th><th>Started (ET)</th><th>Profile</th><th>Status</th><th>Fetched (ET)</th>
                  <th className="num">Rows</th><th className="num">Qual</th><th className="num">Near</th>
                  <th className="num">Filt</th><th className="num">Rej</th><th>Quote time</th><th>Error</th>
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => (
                  <tr key={r.run_id} onClick={() => navigate(`/runs/${r.run_id}`)} tabIndex={0}
                      onKeyDown={(e) => { if (e.key === "Enter") navigate(`/runs/${r.run_id}`); }}>
                    <td><Link to={`/runs/${r.run_id}`} onClick={(e) => e.stopPropagation()}>{r.short_id}</Link></td>
                    <td className="nowrap">{fmtEt(r.started_at)}</td>
                    <td>{r.profile}</td>
                    <td><span className={`badge ${r.status === "OK" ? "run-ok" : "run-error"}`}>{r.status}</span></td>
                    <td className="nowrap">
                      {r.freshness.fetched_at ? <>{fmtEt(r.freshness.fetched_at, false)} <span className="muted">· {fmtAge(ageSeconds(r.freshness.fetched_at, now))} ago</span></> : <span className="muted">—</span>}
                    </td>
                    <td className="num">{r.counts.rows}</td>
                    <td className="num tone-ok">{r.counts.qualified}</td>
                    <td className="num tone-wait">{r.counts.near_miss}</td>
                    <td className="num">{r.counts.filtered_out}</td>
                    <td className="num">{r.counts.rejected}</td>
                    <td><span className="badge fresh-unknown">{r.freshness.quote_freshness}</span></td>
                    <td className="why tone-error">{r.error ? `${r.error.type}: ${r.error.message}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
