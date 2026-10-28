import { useParams, useSearchParams } from "react-router";

import { useRun } from "../api/queries";
import { Freshness } from "../components/Freshness";
import { Panel } from "../components/Panel";
import { ErrorBox, Loading } from "../components/states";
import { ReplayPanel } from "../features/replay/ReplayPanel";
import { ScannerPanelBody } from "../features/scanner/ScannerPanel";
import { StockDrawer } from "../features/scanner/StockDrawer";
import { fmtEt, humanize } from "../lib/format";
import { useNow } from "../lib/useNow";

/** One recorded run: summary, original configs, classified rows, detail, and deterministic replay. */
export function RunPage() {
  const { runId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const run = useRun(runId);
  const now = useNow(1000);
  const rowParam = params.get("row");
  const selected = rowParam !== null && /^\d+$/.test(rowParam) ? Number(rowParam) : undefined;

  if (run.isPending) return <div className="page"><Loading /></div>;
  if (run.isError) return <div className="page"><ErrorBox error={run.error} title="Run not found" /></div>;
  const r = run.data;

  return (
    <div className={`page ${selected !== undefined && r.status === "OK" ? "with-drawer" : ""}`}>
      <div className="page-head">
        <h1>Run {r.short_id}</h1>
        <span className={`badge ${r.status === "OK" ? "run-ok" : "run-error"}`}>{r.status}</span>
        <span className="muted">{r.profile} · started {fmtEt(r.started_at)}</span>
      </div>
      <div className="run-summary">
        <Panel title="Summary">
          <Freshness freshness={r.freshness} nowMs={now} />
          <dl className="kv">
            <div><dt>Run id</dt><dd className="mono">{r.run_id}</dd></div>
            <div><dt>Provider</dt><dd>{r.provider}</dd></div>
            <div><dt>Session</dt><dd>{r.session ?? "—"}</dd></div>
            <div><dt>Recorded</dt><dd>{fmtEt(r.recorded_at)}</dd></div>
            <div><dt>Payload SHA-256</dt><dd className="mono small">{r.payload_sha256 ?? "—"}</dd></div>
          </dl>
          {r.error && <div className="callout callout-error"><strong>{r.error.type}</strong> {r.error.message}</div>}
        </Panel>
        <Panel title="Original configuration">
          <div className="group-title">Finviz discovery filters</div>
          <p className="mono small">{(r.screen_config.filters as string[] | undefined)?.join(", ") || "(none)"}
            {(r.screen_config.tickers as string[] | undefined)?.length ? ` · tickers ${(r.screen_config.tickers as string[]).join(",")}` : ""}</p>
          <div className="group-title">In-play settings used</div>
          <dl className="kv cols">
            {Object.entries(r.in_play_config).map(([k, v]) => (
              <div key={k}><dt>{humanize(k)}</dt><dd className="mono">{Array.isArray(v) ? v.join(", ") || "—" : v == null ? "off" : String(v)}</dd></div>
            ))}
          </dl>
        </Panel>
      </div>
      {r.status === "OK" && (
        <Panel title="Classified stocks" badge={<span className="muted small">click a stock for details</span>}>
          <ScannerPanelBody run={r} selected={selected}
                            onSelect={(row) => setParams({ row: String(row.row_number) }, { replace: true })} />
        </Panel>
      )}
      <ReplayPanel run={r} />
      <StockDrawer runId={selected !== undefined && r.status === "OK" ? r.run_id : undefined} rowNumber={selected}
                   onClose={() => setParams({}, { replace: true })} />
    </div>
  );
}
