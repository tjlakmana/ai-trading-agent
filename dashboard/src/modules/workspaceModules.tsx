// Concrete workspace modules. Only modules backed by real recorded data have a component;
// the rest are rendered by the workspace as labelled "Not available" panels.
import { useRowDetail, useRows } from "../api/queries";
import { ClassBadge, OriginTag } from "../components/badges";
import { Empty, ErrorBox, Loading } from "../components/states";
import { ScannerPanelBody } from "../features/scanner/ScannerPanel";
import { fmtPct } from "../lib/format";
import type { WorkspaceContext, WorkspaceModuleDef } from "./registry";

function NoRun() {
  return <Empty>No successful scan for this profile yet. Use <strong>Run scan now</strong> in the top bar.</Empty>;
}

function ScannerModule({ ctx }: { ctx: WorkspaceContext }) {
  if (!ctx.run) return <NoRun />;
  return (
    <ScannerPanelBody key={ctx.run.run_id} run={ctx.run} initialTab="gappers"
                      selected={ctx.selection?.runId === ctx.run.run_id ? ctx.selection.rowNumber : undefined}
                      onSelect={(r) => ctx.select({ runId: ctx.run!.run_id, rowNumber: r.row_number })} />
  );
}

function StockModule({ ctx }: { ctx: WorkspaceContext }) {
  const watch = useRows(ctx.run?.run_id, { status: ["QUALIFIED", "NEAR_MISS"], sort: "pct_change", limit: 30 });
  const selectedDetail = useRowDetail(ctx.selection?.runId, ctx.selection?.rowNumber); // shared cache with the drawer
  if (!ctx.run) return <NoRun />;
  const current = selectedDetail.data;
  return (
    <div className="stock-module">
      <div className="selected-stock">
        {ctx.selection ? (
          <>
            <span className="muted small">Selected</span>
            <span className="sym">{current?.ticker ?? `row ${ctx.selection.rowNumber}`}</span>
            {current && <ClassBadge status={current.status} />}
            <button className="btn btn-primary" onClick={() => ctx.select(ctx.selection!)}>Show details</button>
          </>
        ) : <span className="muted small">Click a stock in the scanner or the watchlist to open its details.</span>}
      </div>
      <div className="group-title">
        Watchlist <span className="muted small">derived from this run: qualified + near-miss (read-only)</span>
      </div>
      {watch.isPending ? <Loading /> : watch.isError ? <ErrorBox error={watch.error} /> : watch.data.items.length === 0 ? (
        <Empty>No qualified or near-miss stocks in this run.</Empty>
      ) : (
        <div className="watchlist">
          {watch.data.items.map((r) => (
            <button key={r.row_number}
                    className={`chip ${ctx.selection?.rowNumber === r.row_number && ctx.selection.runId === ctx.run!.run_id ? "active" : ""}`}
                    onClick={() => ctx.select({ runId: ctx.run!.run_id, rowNumber: r.row_number })}>
              <span className="sym">{r.ticker}</span>
              <span className={r.status === "QUALIFIED" ? "tone-ok" : "tone-wait"}>{fmtPct(r.calculated.pct_change)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function NewsModule({ ctx }: { ctx: WorkspaceContext }) {
  const rows = useRows(ctx.run?.run_id, { status: ["QUALIFIED", "NEAR_MISS"], sort: "pct_change", limit: 50 });
  if (!ctx.run) return <NoRun />;
  if (rows.isPending) return <Loading />;
  if (rows.isError) return <ErrorBox error={rows.error} />;
  const withNews = rows.data.items.filter((r) => r.news.title);
  return (
    <div className="news-module">
      <p className="hint">
        Finviz&apos;s latest headline per qualified / near-miss stock <OriginTag origin="vendor" />. Headlines are not
        classified: catalyst unknown until the AI agent exists. Finviz does not document the headline time zone.
      </p>
      {withNews.length === 0 ? <Empty>No headlines for these stocks in this run.</Empty> : (
        <ul className="news-list">
          {withNews.map((r) => (
            <li key={r.row_number}>
              <button className="link-btn news-item" onClick={() => ctx.select({ runId: ctx.run!.run_id, rowNumber: r.row_number })}>
                <span className="sym">{r.ticker}</span> <ClassBadge status={r.status} />
                <span className="news-title">{r.news.title}</span>
                <span className="muted small">{r.news.time ?? "time unknown"} · UNCLASSIFIED</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export const WORKSPACE_MODULES: Record<string, WorkspaceModuleDef> = {
  scanner: { id: "scanner", title: "Top Gappers & In-Play Scanner", span: 12, component: ScannerModule,
             collapsedWhenUnavailable: false },
  charts: { id: "charts", title: "Charts · 1-min / 5-min · 9 EMA · VWAP · Volume", span: 8, chartSlot: true,
            collapsedWhenUnavailable: false },
  stock: { id: "stock", title: "Watchlist & Stock Details", span: 4, component: StockModule,
           collapsedWhenUnavailable: false },
  hod_alerts: { id: "hod_alerts", title: "High-of-Day Momentum Alerts", span: 4, collapsedWhenUnavailable: true },
  news: { id: "news", title: "News Catalysts", span: 4, component: NewsModule, collapsedWhenUnavailable: true },
  ai_agent: { id: "ai_agent", title: "AI Agent Analysis & Decisions", span: 4, collapsedWhenUnavailable: true },
  paper: { id: "paper", title: "Paper Trading · Positions · Orders · Risk · P&L", span: 6,
           collapsedWhenUnavailable: true },
  level2: { id: "level2", title: "Level 2 / Time & Sales (optional)", span: 6, collapsedWhenUnavailable: true },
};
