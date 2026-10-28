import type { Module } from "../api/types";

/**
 * The reserved chart area for future Alpaca 1-minute / 5-minute candlesticks.
 * Until a real intraday feed exists it draws NO candles, axes, prices or volume:
 * only the controls that will exist (disabled) and why the chart is empty.
 */
export function ChartSlot({ module, reason }: { module?: Module | undefined; reason: string }) {
  return (
    <div className="chart-slot">
      <div className="chart-toolbar" aria-label="Chart controls (disabled until intraday data exists)">
        <div className="segmented disabled" role="group" aria-label="Timeframe">
          <button disabled>1m</button>
          <button disabled>5m</button>
        </div>
        <div className="chart-overlays">
          <span className="overlay-chip">9 EMA</span>
          <span className="overlay-chip">VWAP</span>
          <span className="overlay-chip">Volume</span>
        </div>
        <span className="muted small chart-symbol">No symbol: select a stock in the scanner</span>
      </div>
      <div className="chart-canvas" role="img" aria-label="Empty chart area: no intraday data source connected">
        <div className="chart-empty">
          <div className="unavailable-icon" aria-hidden>⊘</div>
          <p className="unavailable-title">No intraday data source connected</p>
          <p>{reason}</p>
          <p className="muted small">
            Candlesticks will render here from real Alpaca bars once that feed is integrated
            {module ? ` (data source: ${module.data_source})` : ""}. Nothing is simulated in the meantime.
          </p>
        </div>
      </div>
    </div>
  );
}
