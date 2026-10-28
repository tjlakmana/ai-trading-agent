"""Finviz discovery screen configuration.

The discovery screen is a coarse, vendor-computed pre-filter that narrows the
market to a candidate list. It decides nothing: every candidate is evaluated
again from raw data by strategy/in_play.py, whose InPlayConfig holds the
thresholds that matter. Only verified filter codes are accepted, because
Finviz silently ignores unknown codes.
"""

from dataclasses import dataclass

from core.symbols import MAX_TICKER_LENGTH, TICKER_PATTERN
from data.finviz.schema import (
    COLUMNS,
    CUSTOM_COLUMNS_VIEW,
    DEFAULT_DISCOVERY_FILTERS,
    SECURITY_TYPE,
    VERIFIED_FILTERS,
)


@dataclass(frozen=True)
class FinvizScreenConfig:
    filters: tuple[str, ...] = DEFAULT_DISCOVERY_FILTERS
    tickers: tuple[str, ...] = ()  # optional: restrict the screen to these symbols

    def __post_init__(self) -> None:
        for name in ("filters", "tickers"):
            value = getattr(self, name)
            if not isinstance(value, tuple) or not all(isinstance(v, str) for v in value):
                raise ValueError(f"{name} must be a tuple of strings, got {value!r}")
            if len(set(value)) != len(value):
                raise ValueError(f"{name} contains duplicates: {value!r}")
        unknown = [f for f in self.filters if f not in VERIFIED_FILTERS]
        if unknown:
            raise ValueError(
                f"unverified Finviz filter codes {unknown}; Finviz silently ignores unknown codes, "
                f"so only verified codes are allowed: {sorted(VERIFIED_FILTERS)}"
            )
        bad = [t for t in self.tickers if len(t) > MAX_TICKER_LENGTH or not TICKER_PATTERN.fullmatch(t)]
        if bad:
            raise ValueError(f"malformed tickers: {bad}")
        if not self.filters and not self.tickers:
            raise ValueError("a screen with no filters and no tickers would download the whole market")


def screener_params(config: FinvizScreenConfig) -> dict[str, str]:
    """Query parameters for the screen. Never includes the API key."""
    if not isinstance(config, FinvizScreenConfig):
        raise TypeError(f"config must be a FinvizScreenConfig, got {type(config).__name__}")
    params = {
        "type": SECURITY_TYPE,
        "v": CUSTOM_COLUMNS_VIEW,
        "c": ",".join(str(i) for i in sorted(COLUMNS)),
    }
    if config.filters:
        params["f"] = ",".join(config.filters)
    if config.tickers:
        params["t"] = ",".join(config.tickers)
    return params
