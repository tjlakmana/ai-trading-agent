"""Dashboard modules and their availability, decided by the backend.

Each module states the data it needs. A module is AVAILABLE or PARTIAL only
when a real data source for it exists. Everything else is UNAVAILABLE and
says why, so the frontend can label it instead of drawing placeholder data.

Adding a source later (for example an Alpaca market-data adapter) means
setting its capability flag in Capabilities. The registry and the frontend
layout stay the same.
"""

from dataclasses import asdict, dataclass
from enum import Enum


class ModuleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIAL = "PARTIAL"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class Capabilities:
    finviz_configured: bool  # a well-formed FINVIZ_API_KEY exists (value never exposed)
    history_available: bool  # the scanner history database exists
    intraday_feed: bool = False  # real-time trades/bars (future: Alpaca adapter)
    news_classification: bool = False  # AI catalyst classification (future: agent/)
    agent: bool = False
    paper_trading: bool = False  # paper execution + trade memory
    level2: bool = False  # Level 2 / Time & Sales feed


@dataclass(frozen=True)
class ModuleInfo:
    id: str
    title: str
    status: ModuleStatus
    data_source: str
    detail: str


def _status(ok: bool, partial: bool = False) -> ModuleStatus:
    if ok:
        return ModuleStatus.AVAILABLE
    return ModuleStatus.PARTIAL if partial else ModuleStatus.UNAVAILABLE


def modules(c: Capabilities) -> tuple[ModuleInfo, ...]:
    scan_data = c.history_available or c.finviz_configured
    scanner_detail = ("Recorded Finviz scans classified by the deterministic in-play filter. Top Gappers "
                      "ranks by our gap % (regular-session open vs previous close)."
                      if scan_data else "Add FINVIZ_API_KEY to .env and run a scan to populate it.")
    return (
        ModuleInfo("scanner", "Top Gappers & In-Play Scanner", _status(scan_data),
                   "Finviz Elite screener + scanner history", scanner_detail),
        ModuleInfo("hod_alerts", "High-of-Day Momentum Alerts", _status(c.intraday_feed),
                   "real-time intraday trades (not integrated)",
                   "Requires a real-time intraday feed. Finviz day highs are snapshots at fetch time, "
                   "not alerts."),
        ModuleInfo("stock", "Watchlist & Stock Details",
                   ModuleStatus.PARTIAL if c.history_available else ModuleStatus.UNAVAILABLE,
                   "scanner history",
                   "Details and ticker history from recorded scans. The watchlist is derived from the latest "
                   "run (qualified + near-miss); a manual watchlist is not built yet."),
        ModuleInfo("charts", "1-min / 5-min Charts (9 EMA, VWAP, volume)", _status(c.intraday_feed),
                   "intraday bars (not integrated)", "Requires intraday 1-minute bars."),
        ModuleInfo("news", "News Catalysts",
                   ModuleStatus.AVAILABLE if c.news_classification
                   else (ModuleStatus.PARTIAL if c.history_available else ModuleStatus.UNAVAILABLE),
                   "Finviz latest headline per stock",
                   "Shows Finviz's latest headline and time as vendor data. Catalysts are not classified "
                   "(catalyst unknown) until the AI agent exists."),
        ModuleInfo("ai_agent", "AI Agent Analysis", _status(c.agent),
                   "agent/ (not built)", "The AI agent is not implemented yet."),
        ModuleInfo("paper", "Paper Trading: Positions, Orders, Risk, Performance", _status(c.paper_trading),
                   "paper execution + trade memory (not built)",
                   "Paper execution and trade memory are not implemented. No orders can be placed."),
        ModuleInfo("level2", "Level 2 / Time & Sales (optional)", _status(c.level2),
                   "Level 2 feed (none)", "No Level 2 or Time & Sales data source is available."),
        ModuleInfo("history", "Scan History & Replay",
                   ModuleStatus.AVAILABLE if c.history_available else ModuleStatus.UNAVAILABLE,
                   "scanner history", "Every recorded scan attempt, ticker history, deterministic replay."),
    )


def module_dicts(c: Capabilities) -> list[dict]:
    return [{**asdict(m), "status": m.status.value} for m in modules(c)]
