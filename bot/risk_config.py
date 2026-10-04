"""Risk limits enforced by the bot.

Owned by the bot and defined in code. Never read from agent output,
environment variables, or proposals. The agent cannot import this package
(enforced by tests/test_architecture.py).

DEFAULTS ARE DEVELOPMENT / TESTING VALUES ONLY. They are chosen so the sizing
math is easy to verify by hand and every limit is reachable in tests. They are
NOT recommendations for real-money trading.
"""

import math
from dataclasses import dataclass, fields

from bot.validation import is_number


@dataclass(frozen=True)
class RiskConfig:
    # Max fraction of current equity that may be lost on one trade if stopped out.
    max_risk_per_trade_pct: float = 0.01
    # Max fraction of current equity held in a single ticker (market value).
    max_position_pct: float = 0.20
    # Max equity loss from start-of-day equity before new BUYs are blocked.
    max_daily_loss_pct: float = 0.03

    def __post_init__(self) -> None:
        for f in fields(self):
            value = getattr(self, f.name)
            if not is_number(value) or not math.isfinite(value) or not 0 < value <= 1:
                raise ValueError(f"{f.name} must be a number in (0, 1], got {value!r}")
