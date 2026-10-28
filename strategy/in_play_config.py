"""Configuration for the Version 1 in-play stock filter.

Experimental, Ross Cameron-INSPIRED small-cap momentum hypothesis. These values
do NOT claim to reproduce Ross Cameron's exact rules. Every default is a
Version 1 development hypothesis expected to change after backtesting and
paper trading.

Each criterion has a category:
    HARD       - must pass; failure or missing data means not qualified.
    PREFERRED  - evaluated and recorded; failure only adds a warning.
    OFF        - not evaluated (raw inputs are still preserved in the result).
Numeric thresholds may be set to None to disable that check.
Moving a criterion between categories is a config change, never a code change.
"""

import math
from dataclasses import dataclass, field
from enum import Enum
from numbers import Real

from core.market import CatalystType


class Level(str, Enum):
    HARD = "HARD"
    PREFERRED = "PREFERRED"
    OFF = "OFF"


def is_number(value) -> bool:
    # bool is a subclass of int; True/False are never valid numbers here.
    return isinstance(value, Real) and not isinstance(value, bool)


def _is_positive_number(value) -> bool:
    return is_number(value) and math.isfinite(value) and value > 0


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


@dataclass(frozen=True)
class InPlayConfig:
    # --- HARD (V1 experimental) ---
    # $2-$20 small-cap price range.
    min_price: float | None = 2.00
    max_price: float | None = 20.00
    # Minimum % change from previous close (0.10 = +10%).
    min_pct_change: float | None = 0.10
    # Minimum cumulative volume / average FULL-DAY volume. Not time-of-day RVOL.
    min_volume_vs_avg_daily: float | None = 3.0
    max_float_shares: int | None = 20_000_000
    # Minimum session volume so far, in shares. Disabled (None) by default.
    # Which one applies follows ScannerSnapshot: open_price None means the
    # snapshot is from before the regular-session open (premarket).
    min_cumulative_volume: int | None = None  # regular session (open_price set)
    min_premarket_cumulative_volume: int | None = None  # premarket (open_price None)

    # --- PREFERRED (V1 experimental) ---
    preferred_max_float_shares: int | None = 10_000_000
    preferred_volume_vs_avg_daily: float | None = 5.0

    # --- Criteria whose category is itself a hypothesis ---
    # PREFERRED until a news/catalyst data source exists.
    catalyst_level: Level = Level.PREFERRED
    # PREFERRED; 20% is a V1 placeholder, not a known rule.
    room_level: Level = Level.PREFERRED
    min_room_to_resistance_pct: float = 0.20

    # Catalyst types that add a warning (e.g. dilutive offerings).
    negative_catalyst_types: frozenset = field(
        default_factory=lambda: frozenset({CatalystType.OFFERING})
    )

    def __post_init__(self) -> None:
        for name in ("min_price", "max_price", "min_pct_change",
                     "min_volume_vs_avg_daily", "preferred_volume_vs_avg_daily"):
            value = getattr(self, name)
            if value is not None and not _is_positive_number(value):
                raise ValueError(f"{name} must be a positive number or None, got {value!r}")
        if not _is_positive_number(self.min_room_to_resistance_pct):
            raise ValueError(
                f"min_room_to_resistance_pct must be a positive number, got {self.min_room_to_resistance_pct!r}"
            )
        for name in ("max_float_shares", "preferred_max_float_shares",
                     "min_cumulative_volume", "min_premarket_cumulative_volume"):
            value = getattr(self, name)
            if value is not None and not _is_positive_int(value):
                raise ValueError(f"{name} must be a positive whole number or None, got {value!r}")

        if self.min_price is not None and self.max_price is not None and self.min_price >= self.max_price:
            raise ValueError(f"min_price {self.min_price} must be below max_price {self.max_price}")
        if (self.max_float_shares is not None and self.preferred_max_float_shares is not None
                and self.preferred_max_float_shares > self.max_float_shares):
            raise ValueError("preferred_max_float_shares must not exceed max_float_shares")
        if (self.min_volume_vs_avg_daily is not None and self.preferred_volume_vs_avg_daily is not None
                and self.preferred_volume_vs_avg_daily < self.min_volume_vs_avg_daily):
            raise ValueError("preferred_volume_vs_avg_daily must not be below min_volume_vs_avg_daily")

        for name in ("catalyst_level", "room_level"):
            if not isinstance(getattr(self, name), Level):
                raise ValueError(f"{name} must be a Level, got {getattr(self, name)!r}")
        if not isinstance(self.negative_catalyst_types, frozenset) or not all(
            isinstance(t, CatalystType) for t in self.negative_catalyst_types
        ):
            raise ValueError("negative_catalyst_types must be a frozenset of CatalystType")
