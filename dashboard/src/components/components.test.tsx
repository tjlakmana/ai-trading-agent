import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { Freshness as FreshnessData } from "../api/types";
import { ClassBadge, OriginLegend, OriginTag } from "./badges";
import { ChartSlot } from "./ChartSlot";
import { Freshness } from "./Freshness";
import { UnavailablePanel } from "./Panel";

const text = (html: string) => html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();

describe("UnavailablePanel", () => {
  it("explains what is missing and shows no numbers", () => {
    const html = renderToStaticMarkup(
      <UnavailablePanel title="High-of-Day Momentum Alerts"
                        module={{ id: "hod_alerts", title: "HOD", status: "UNAVAILABLE",
                                  data_source: "real-time intraday trades (not integrated)",
                                  detail: "Requires a real-time intraday feed." }} />);
    const t = text(html);
    expect(t).toContain("Not available");
    expect(t).toContain("Unavailable");
    expect(t).toContain("Requires a real-time intraday feed.");
    expect(t).toContain("real-time intraday trades (not integrated)");
    expect(t).not.toMatch(/\d/); // no placeholder prices, volumes or P&L
  });
});

describe("collapsible UnavailablePanel", () => {
  const module = { id: "paper", title: "Paper", status: "UNAVAILABLE" as const, data_source: "paper execution (not built)",
                   detail: "Paper execution and trade memory are not implemented." };
  it("collapses to a one-line bar that still says why", () => {
    const html = renderToStaticMarkup(<UnavailablePanel title="Paper Trading" module={module} collapsed onToggle={() => {}} />);
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("panel-collapsed");
    expect(text(html)).toContain("Paper execution and trade memory are not implemented.");
    expect(text(html)).not.toContain("Not available"); // body hidden while collapsed
  });
  it("expands with a collapse control", () => {
    const html = renderToStaticMarkup(<UnavailablePanel title="Paper Trading" module={module} onToggle={() => {}} />);
    expect(html).toContain('aria-expanded="true"');
    expect(text(html)).toContain("Not available");
  });
  it("has no toggle when not collapsible", () => {
    expect(renderToStaticMarkup(<UnavailablePanel title="X" module={module} />)).not.toContain("aria-expanded");
  });
});

describe("ChartSlot", () => {
  it("reserves the chart area without drawing any market data", () => {
    const html = renderToStaticMarkup(<ChartSlot reason="Requires intraday 1-minute bars." />);
    const t = text(html);
    expect(t).toContain("No intraday data source connected");
    expect(t).toContain("Requires intraday 1-minute bars.");
    expect(t).toContain("Nothing is simulated");
    expect(html).not.toMatch(/<svg|<canvas|<path/); // no rendered chart
    expect(t).not.toMatch(/\$\d|\d+\.\d+|\d{3,}/); // no prices, decimals or volumes
    expect(html.match(/disabled=""/g)?.length).toBe(2); // timeframe buttons disabled
  });
});

describe("origin labels", () => {
  it("tags raw, calculated and Finviz-calculated values distinctly", () => {
    expect(text(renderToStaticMarkup(<OriginTag origin="raw" />))).toBe("RAW");
    expect(text(renderToStaticMarkup(<OriginTag origin="calc" />))).toBe("OURS");
    const vendor = renderToStaticMarkup(<OriginTag origin="vendor" />);
    expect(text(vendor)).toBe("FV");
    expect(vendor).toContain("never used in our checks");
    expect(text(renderToStaticMarkup(<OriginLegend />))).toContain("Finviz-calculated value");
  });
  it("labels every row class", () => {
    expect(text(renderToStaticMarkup(<ClassBadge status="NEAR_MISS" />))).toBe("Near-miss");
    expect(text(renderToStaticMarkup(<ClassBadge status="REJECTED" />))).toBe("Rejected");
  });
});

describe("Freshness", () => {
  const f: FreshnessData = {
    fetched_at: "2026-10-28T18:57:39Z", fetched_at_et: "2026-10-28 14:57:39 EDT", quote_time: null,
    quote_freshness: "UNKNOWN", seconds_since_fetch: 90, note: "Finviz provides no quote timestamp",
  };
  it("shows the fetch time and that the quote time is unknown", () => {
    const t = text(renderToStaticMarkup(<Freshness freshness={f} nowMs={Date.parse("2026-10-28T19:00:39Z")} />));
    expect(t).toContain("Fetched 2026-10-28 14:57:39 EDT");
    expect(t).toContain("3m ago");
    expect(t).toContain("Quote time: UNKNOWN");
  });
  it("handles failed runs with no data", () => {
    const t = text(renderToStaticMarkup(<Freshness freshness={{ ...f, fetched_at: null }} nowMs={0} />));
    expect(t).toContain("no data received");
  });
});
