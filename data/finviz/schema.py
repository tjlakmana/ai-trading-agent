"""Verified Finviz Elite Screener API facts: endpoint, columns, filter codes, units.

Everything here was checked against a live Finviz Elite response on
2026-10-28. Verify any new column or filter code the same way before adding
it. Finviz silently ignores unknown filter codes, so an unverified code would
quietly widen the screen instead of failing.
"""

ENDPOINT = "https://elite.finviz.com/export/screener"
API_KEY_ENV_VAR = "FINVIZ_API_KEY"
SECURITY_TYPE = "stocks"
# View 152 with c=<column indices> returns exactly the requested columns.
CUSTOM_COLUMNS_VIEW = "152"

# --- CSV header names --------------------------------------------------------

TICKER = "Ticker"
COMPANY = "Company"
EXCHANGE = "Exchange"
# Raw market data
PRICE = "Price"
PREV_CLOSE = "Prev Close"
OPEN = "Open"
HIGH = "High"
LOW = "Low"
VOLUME = "Volume"
AVERAGE_VOLUME = "Average Volume"
SHARES_FLOAT = "Shares Float"
TRADES = "Trades"
# Finviz-calculated (vendor discovery data only)
RELATIVE_VOLUME = "Relative Volume"
CHANGE = "Change"
CHANGE_FROM_OPEN = "Change from Open"
GAP = "Gap"
PERF_1M = "Performance (1 Minute)"
PERF_5M = "Performance (5 Minutes)"
PERF_10M = "Performance (10 Minutes)"
PERF_15M = "Performance (15 Minutes)"
PERF_30M = "Performance (30 Minutes)"
PERF_1H = "Performance (1 Hour)"
# News (recorded only; no catalyst classification in V1)
NEWS_TIME = "News Time"
NEWS_TITLE = "News Title"

# Column index -> exact CSV header text.
COLUMNS: dict[int, str] = {
    1: TICKER, 2: COMPANY, 25: SHARES_FLOAT, 60: CHANGE_FROM_OPEN, 61: GAP,
    63: AVERAGE_VOLUME, 64: RELATIVE_VOLUME, 65: PRICE, 66: CHANGE, 67: VOLUME,
    81: PREV_CLOSE, 86: OPEN, 87: HIGH, 88: LOW, 89: TRADES,
    90: PERF_1M, 93: PERF_5M, 94: PERF_10M, 95: PERF_15M, 96: PERF_30M, 97: PERF_1H,
    129: EXCHANGE, 135: NEWS_TIME, 137: NEWS_TITLE,
}
# Indices are NOT positions in the full column list: 0-99 are contiguous, 100-124
# do not exist, and the columns from "All-Time High" (125) onward follow. Each
# index above was confirmed individually against the live API.
EXPECTED_HEADERS = frozenset(COLUMNS.values())

# --- Units (verified with AAPL/TSLA magnitudes) ------------------------------

AVERAGE_VOLUME_MULTIPLIER = 1_000  # "Average Volume" is in thousands of shares
SHARES_FLOAT_MULTIPLIER = 1_000_000  # "Shares Float" is in millions of shares
# "Volume" is whole shares; Price, Prev Close, Open, High and Low are dollars.

# --- Verified filter codes ---------------------------------------------------

# Finviz evaluates these on its own data; they only narrow the discovery
# universe. The in-play filter re-checks candidates from raw data.
VERIFIED_FILTERS: dict[str, str] = {
    "sh_price_2to20": "price $2 to $20",
    "sh_relvol_o2": "Finviz relative volume over 2",
    "sh_curvol_o500": "current volume over 500K shares",
    "sh_float_u20": "float under 20M shares",
    "ta_change_u": "up on the day",
}
# V1 starting hypothesis, not Warrior Trading's exact rules.
DEFAULT_DISCOVERY_FILTERS: tuple[str, ...] = tuple(VERIFIED_FILTERS)
