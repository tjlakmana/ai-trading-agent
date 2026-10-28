"""Finviz Elite Screener API provider: stock discovery only.

    FinvizScreenConfig -> FinvizClient (HTTP) -> parse_screener_csv -> FinvizRecord
        -> ScannerSnapshot -> strategy.in_play.evaluate_universe -> FinvizScan

Finviz narrows the market to a candidate list with its own server-side
filters. It decides nothing: every candidate's raw data (price, previous
close, open, volume, average volume, float) is re-evaluated by the
deterministic in-play filter. Finviz-calculated values (Relative Volume,
Change, Gap, recent Performance) are kept separately as vendor discovery data
and never substitute for our own calculations.

Finviz provides no quote timestamp: fetched_at is recorded, and quote
freshness is always UNKNOWN. This package never imports bot/, execution/ or
agent/ and cannot place orders. Manual run: python -m data.finviz
"""
