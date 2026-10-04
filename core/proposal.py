"""Trade proposal contract: the only thing the agent hands to the bot.

Data only. A TradeProposal is a *request*; nothing here decides whether it is
valid or allowed. That is the bot's job (see bot/validation.py).

Action semantics (Version 1, long-only):
    BUY  - open or add to a long position.
           entry      = proposed entry price
           stop_loss  = required, below entry
           take_profit = optional, above entry (some strategies may use
                         other exit mechanisms)
    SELL - close an EXISTING long position. Never opens a short.
           There is no quantity field: proposals never specify size. Quantities
           (including any future partial exits) are decided by the bot.
           entry      = proposed exit price (optional; None means exit at market)
           stop_loss / take_profit = not used, must be None
           Ownership of the position is not checked yet; that will be added
           when portfolio state exists.
    HOLD - no trade. All price fields must be None. Recorded for auditability.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class Action(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TradeProposal:
    ticker: str
    action: Action
    confidence: float
    reasoning: str
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    created_at: datetime = field(default_factory=_utc_now)
