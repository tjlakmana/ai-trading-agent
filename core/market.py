"""Market scanner data contract.

Data only. A ScannerSnapshot holds RAW inputs for one ticker at one moment.
Derived values (percent change, gap, volume ratios, room to resistance) are
computed deterministically by strategy/, never stored here and never taken
from a vendor's pre-computed fields or from an AI.

Future producers: data/ adapters. Consumers: strategy/, memory/, the agent (read).
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class CatalystType(str, Enum):
    EARNINGS = "EARNINGS"
    FDA = "FDA"
    CONTRACT = "CONTRACT"
    PARTNERSHIP = "PARTNERSHIP"
    MERGER_ACQUISITION = "MERGER_ACQUISITION"
    OFFERING = "OFFERING"  # dilutive; flagged as a negative catalyst by default
    OTHER_NEWS = "OTHER_NEWS"


@dataclass(frozen=True)
class Catalyst:
    present: bool
    type: CatalystType | None
    headline: str | None
    # Provenance: "manual", "news_feed", later possibly "agent". The AI may
    # classify news into a Catalyst; it never decides whether a threshold passed.
    source: str


@dataclass(frozen=True)
class ScannerSnapshot:
    ticker: str
    as_of: datetime  # timezone-aware
    source: str  # data provenance, e.g. "manual", "fixture"
    price: float
    previous_close: float
    open_price: float | None  # None before the regular-session open
    cumulative_volume: int  # session volume so far
    average_daily_volume: float | None  # average FULL-DAY volume
    premarket_volume: int | None
    float_shares: int | None
    catalyst: Catalyst | None  # None = not checked / unknown
    daily_resistance: float | None  # nearest overhead daily resistance price
    # False = resistance unknown. True with daily_resistance None = checked, none overhead.
    resistance_checked: bool
