import { Link, NavLink, Outlet } from "react-router";

import { useHealth, useModules } from "../api/queries";
import { ScanControl } from "../features/scan/ScanControl";

/** App frame: top bar (status + Run scan now), navigation, and the routed page. */
export function Shell() {
  const health = useHealth();
  const modules = useModules();
  const h = health.data;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>▲</span>
          <span className="brand-name">Momentum Desk</span>
          <span className="badge research">RESEARCH ONLY</span>
        </div>
        <ScanControl />
        <div className="status-chips">
          <span className={`chip-status ${health.isError ? "bad" : h ? "good" : ""}`}
                title={health.isError ? String(health.error) : "Backend reachable"}>
            API {health.isError ? "offline" : h ? "online" : "…"}
          </span>
          {h && (
            <>
              <span className={`chip-status ${h.finviz_key_configured ? "good" : "bad"}`}
                    title="Whether FINVIZ_API_KEY is configured. The key itself is never sent to the browser.">
                Finviz key {h.finviz_key_configured ? "configured" : "missing"}
              </span>
              <span className="chip-status locked" title="The dashboard cannot place orders.">
                Orders {h.order_execution_enabled ? "ENABLED" : "disabled"}
              </span>
            </>
          )}
        </div>
      </header>
      <nav className="sidenav" aria-label="Main">
        <NavLink to="/" end>Workspace</NavLink>
        <NavLink to="/history">Scan history</NavLink>
        <NavLink to="/ticker">Ticker history</NavLink>
        <div className="nav-section">Modules</div>
        {(modules.data ?? []).filter((m) => m.id !== "history").map((m) => (
          <Link key={m.id} to={`/#module-${m.id}`} className="nav-module" title={m.detail}>
            <span className={`dot dot-${m.status.toLowerCase()}`} aria-hidden /> {m.title}
            {m.status === "UNAVAILABLE" && <span className="muted small"> · unavailable</span>}
          </Link>
        ))}
      </nav>
      <main className="main">
        <Outlet />
        <footer className="footer muted small">
          Research and paper-trading preparation only. Finviz data is a snapshot: fetched_at is when we received it;
          Finviz provides no quote timestamp, so quote freshness is UNKNOWN. Nothing here is a trade signal.
        </footer>
      </main>
    </div>
  );
}
