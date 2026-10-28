"""Market data and external information sources.

Implemented:
    finviz/          Finviz Elite Screener API: stock discovery -> ScannerSnapshot
    market_hours.py  US equity session classification (premarket/regular/...)

Eventually: adapters for TradingView (via MCP), a real-time intraday feed,
price/volume history, technical indicators, financial news, and sentiment.
Read-only inputs consumed by the strategy, the agent (for analysis), and the
bot (for price checks). Must never import bot/, execution/, agent/ or an LLM
SDK (enforced by tests/test_architecture.py).
"""
