"""Account and portfolio state contract.

Data only. Account state always comes from the bot's source of truth
(later: the paper broker), never from the agent. Equity and all other
derived values are computed by the bot, not stored here.

Version 1 is long-only: every position is a positive whole-share quantity.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Position:
    ticker: str
    quantity: int  # whole shares, > 0
    market_price: float  # latest price, used to value the position


@dataclass(frozen=True)
class AccountState:
    cash: float
    positions: tuple[Position, ...]
    start_of_day_equity: float  # equity at the start of the trading day
