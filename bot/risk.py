"""Deterministic risk manager: the authority on whether a proposal may execute.

Single entry point: evaluate(proposal, account, config) -> RiskDecision.

    1. Structural validation (bot/validation.py)  invalid -> REJECT (VALIDATION)
    2. Account state checks                       invalid -> REJECT (ACCOUNT)
    3. By action:
         HOLD -> NO_ACTION (never executes)
         SELL -> APPROVE closing the entire existing long position, else REJECT
         BUY  -> daily-loss check, then position sizing -> APPROVE / REJECT

Only Decision.APPROVE may ever reach execution. Agent confidence plays no part
in sizing or approval. No LLM participates in any step.

BUY sizing (all quantities are whole shares, rounded down):
    equity               = cash + sum(quantity * market_price)
    stop_distance        = entry - stop_loss
    daily_loss           = max(0, start_of_day_equity - equity)
    daily_loss_limit     = start_of_day_equity * max_daily_loss_pct
    remaining_daily_loss = max(0, daily_loss_limit - daily_loss)
    risk_basis           = min(equity, start_of_day_equity)
    per_trade_risk_limit = risk_basis * max_risk_per_trade_pct
    risk_budget          = min(per_trade_risk_limit, remaining_daily_loss)
    qty_by_risk          = floor(risk_budget / stop_distance)
    qty_by_exposure      = floor((equity * max_position_pct - existing_value) / entry)
    qty_by_cash          = floor(cash / entry)
    quantity             = min(qty_by_risk, qty_by_exposure, qty_by_cash)

Intraday profits never increase per-trade risk or the daily-loss allowance.
Intraday losses reduce both.
"""

import math
from dataclasses import dataclass
from enum import Enum

from bot.risk_config import RiskConfig
from bot.validation import MAX_TICKER_LENGTH, TICKER_PATTERN, is_number, validate_proposal
from core.portfolio import AccountState, Position
from core.proposal import Action, TradeProposal

# Relative tolerance for float noise, e.g. 1000 / (1.3 - 1.2) = 9999.99999999999.
TOLERANCE = 1e-9


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    NO_ACTION = "NO_ACTION"  # HOLD: nothing to execute


class Stage(str, Enum):
    VALIDATION = "VALIDATION"
    ACCOUNT = "ACCOUNT"
    RISK = "RISK"


@dataclass(frozen=True)
class DailyLossStatus:
    daily_loss: float
    daily_loss_limit: float
    remaining_daily_loss: float
    limit_reached: bool


@dataclass(frozen=True)
class SizingBreakdown:
    """Every number used to size a BUY, recorded for audit."""

    equity: float
    stop_distance: float
    risk_basis: float  # min(equity, start_of_day_equity)
    per_trade_risk_limit: float  # risk_basis * max_risk_per_trade_pct
    daily_loss: float
    daily_loss_limit: float
    remaining_daily_loss: float
    risk_budget: float  # min(per_trade_risk_limit, remaining_daily_loss)
    existing_position_value: float
    max_position_value: float  # equity * max_position_pct
    qty_by_risk: int
    qty_by_exposure: int
    qty_by_cash: int
    quantity: int
    binding_constraint: str  # "risk" | "daily_loss" | "exposure" | "cash"
    planned_risk: float  # quantity * stop_distance
    position_value: float  # quantity * entry


@dataclass(frozen=True)
class RiskDecision:
    decision: Decision
    stage: Stage
    proposal: TradeProposal | None  # None if the input was not a TradeProposal
    quantity: int  # >= 1 only for APPROVE, otherwise 0
    reasons: tuple[str, ...]
    sizing: SizingBreakdown | None  # BUY that reached sizing only
    config: RiskConfig

    def __post_init__(self) -> None:
        if not isinstance(self.quantity, int) or isinstance(self.quantity, bool):
            raise ValueError("quantity must be an int")
        if self.decision is Decision.APPROVE and self.quantity < 1:
            raise ValueError("APPROVE requires quantity >= 1")
        if self.decision is not Decision.APPROVE and self.quantity != 0:
            raise ValueError(f"{self.decision.value} requires quantity 0")

    @property
    def is_approved(self) -> bool:
        return self.decision is Decision.APPROVE


# --- Pure helpers ------------------------------------------------------------


def floor_shares(raw: float) -> int:
    """Round a share count down, tolerating float noise just below a whole number."""
    return max(0, math.floor(raw * (1 + TOLERANCE)))


def compute_equity(account: AccountState) -> float:
    return account.cash + sum(p.quantity * p.market_price for p in account.positions)


def daily_loss_status(account: AccountState, config: RiskConfig) -> DailyLossStatus:
    sod = account.start_of_day_equity
    daily_loss = max(0.0, sod - compute_equity(account))
    limit = sod * config.max_daily_loss_pct
    limit_reached = daily_loss >= limit * (1 - TOLERANCE)
    remaining = 0.0 if limit_reached else max(0.0, limit - daily_loss)
    return DailyLossStatus(daily_loss, limit, remaining, limit_reached)


def _is_finite_number(value) -> bool:
    return is_number(value) and math.isfinite(value)


def _validate_position(i: int, p, errors: list[str]) -> None:
    if not isinstance(p, Position):
        errors.append(f"positions[{i}] must be a Position, got {type(p).__name__}")
        return
    if (not isinstance(p.ticker, str) or len(p.ticker) > MAX_TICKER_LENGTH
            or not TICKER_PATTERN.fullmatch(p.ticker)):
        errors.append(f"positions[{i}] ticker {p.ticker!r} is malformed")
    if not isinstance(p.quantity, int) or isinstance(p.quantity, bool) or p.quantity < 1:
        errors.append(f"positions[{i}] quantity must be a whole number >= 1, got {p.quantity!r}")
    if not _is_finite_number(p.market_price) or p.market_price <= 0:
        errors.append(f"positions[{i}] market_price must be a positive number, got {p.market_price!r}")


def validate_account(account) -> tuple[str, ...]:
    """Return every problem with the account state. Empty tuple means usable. Never raises."""
    if not isinstance(account, AccountState):
        return (f"expected AccountState, got {type(account).__name__}",)

    errors: list[str] = []
    if not _is_finite_number(account.cash) or account.cash < 0:
        errors.append(f"cash must be a non-negative number, got {account.cash!r}")
    sod = account.start_of_day_equity
    if not _is_finite_number(sod) or sod <= 0:
        errors.append(f"start_of_day_equity must be a positive number, got {sod!r}")

    if not isinstance(account.positions, tuple):
        errors.append("positions must be a tuple")
    else:
        for i, p in enumerate(account.positions):
            _validate_position(i, p, errors)
        tickers = [p.ticker for p in account.positions if isinstance(p, Position)]
        duplicates = sorted({t for t in tickers if tickers.count(t) > 1}, key=str)
        if duplicates:
            errors.append(f"duplicate positions for {duplicates}")

    if not errors and compute_equity(account) <= 0:
        errors.append("equity must be positive")
    return tuple(errors)


def size_buy(proposal: TradeProposal, account: AccountState, config: RiskConfig) -> SizingBreakdown:
    """Compute BUY quantity under every limit. Assumes validated inputs."""
    entry = proposal.entry
    equity = compute_equity(account)
    stop_distance = entry - proposal.stop_loss
    daily = daily_loss_status(account, config)

    risk_basis = min(equity, account.start_of_day_equity)
    per_trade_risk_limit = risk_basis * config.max_risk_per_trade_pct
    risk_budget = min(per_trade_risk_limit, daily.remaining_daily_loss)
    existing_value = sum(
        p.quantity * p.market_price for p in account.positions if p.ticker == proposal.ticker
    )
    max_position_value = equity * config.max_position_pct

    qty_by_risk = floor_shares(risk_budget / stop_distance)
    qty_by_exposure = floor_shares(max(0.0, max_position_value - existing_value) / entry)
    qty_by_cash = floor_shares(account.cash / entry)
    quantity = min(qty_by_risk, qty_by_exposure, qty_by_cash)

    # Ties resolve in this order; "daily_loss" means the daily allowance capped the risk budget.
    risk_label = "daily_loss" if daily.remaining_daily_loss < per_trade_risk_limit else "risk"
    candidates = ((risk_label, qty_by_risk), ("exposure", qty_by_exposure), ("cash", qty_by_cash))
    binding = next(name for name, qty in candidates if qty == quantity)

    return SizingBreakdown(
        equity=equity,
        stop_distance=stop_distance,
        risk_basis=risk_basis,
        per_trade_risk_limit=per_trade_risk_limit,
        daily_loss=daily.daily_loss,
        daily_loss_limit=daily.daily_loss_limit,
        remaining_daily_loss=daily.remaining_daily_loss,
        risk_budget=risk_budget,
        existing_position_value=existing_value,
        max_position_value=max_position_value,
        qty_by_risk=qty_by_risk,
        qty_by_exposure=qty_by_exposure,
        qty_by_cash=qty_by_cash,
        quantity=quantity,
        binding_constraint=binding,
        planned_risk=quantity * stop_distance,
        position_value=quantity * entry,
    )


# --- Per-action evaluation ---------------------------------------------------


def _evaluate_buy(p: TradeProposal, account: AccountState, config: RiskConfig) -> RiskDecision:
    s = size_buy(p, account, config)
    reasons: list[str] = []

    if s.daily_loss_limit > 0 and s.remaining_daily_loss == 0:
        reasons.append(
            f"daily loss limit reached: loss ${s.daily_loss:,.2f} >= limit ${s.daily_loss_limit:,.2f}"
        )
    elif s.qty_by_risk == 0:
        budget_name = "remaining daily-loss allowance" if s.binding_constraint == "daily_loss" else "risk budget"
        reasons.append(
            f"{budget_name} ${s.risk_budget:,.2f} is less than the ${s.stop_distance:,.2f} "
            f"stop-out risk of one share"
        )
    if s.qty_by_exposure == 0:
        reasons.append(
            f"exposure limit: ${s.existing_position_value:,.2f} already held in {p.ticker}, "
            f"max ${s.max_position_value:,.2f}; no room for one share at ${p.entry:,.2f}"
        )
    if s.qty_by_cash == 0:
        reasons.append(f"insufficient cash: ${account.cash:,.2f} available, one share costs ${p.entry:,.2f}")

    if reasons:
        return RiskDecision(Decision.REJECT, Stage.RISK, p, 0, tuple(reasons), s, config)
    reason = f"approved {s.quantity} shares of {p.ticker}; size limited by {s.binding_constraint}"
    return RiskDecision(Decision.APPROVE, Stage.RISK, p, s.quantity, (reason,), s, config)


def _evaluate_sell(p: TradeProposal, account: AccountState, config: RiskConfig) -> RiskDecision:
    # SELL closes an existing long position in full. Not blocked by the daily-loss
    # limit: exiting reduces exposure. Without a position there is nothing to sell,
    # which is also what makes short selling impossible.
    held = next((pos for pos in account.positions if pos.ticker == p.ticker), None)
    if held is None:
        reason = f"no long position in {p.ticker} to close (short selling is not allowed)"
        return RiskDecision(Decision.REJECT, Stage.RISK, p, 0, (reason,), None, config)
    reason = f"closing entire long position: {held.quantity} shares of {p.ticker}"
    return RiskDecision(Decision.APPROVE, Stage.RISK, p, held.quantity, (reason,), None, config)


def evaluate(proposal, account, config: RiskConfig) -> RiskDecision:
    """Decide APPROVE / REJECT / NO_ACTION for a proposal. The only public entry point.

    Never raises for bad proposals or account data (they are rejected).
    Raises TypeError if config is not a RiskConfig: that is a programming error
    in bot code, not untrusted input.
    """
    if not isinstance(config, RiskConfig):
        raise TypeError(f"config must be a RiskConfig, got {type(config).__name__}")

    validation = validate_proposal(proposal)
    if not validation.is_valid:
        p = proposal if isinstance(proposal, TradeProposal) else None
        return RiskDecision(Decision.REJECT, Stage.VALIDATION, p, 0, validation.errors, None, config)

    account_errors = validate_account(account)
    if account_errors:
        return RiskDecision(Decision.REJECT, Stage.ACCOUNT, proposal, 0, account_errors, None, config)

    if proposal.action is Action.HOLD:
        return RiskDecision(
            Decision.NO_ACTION, Stage.RISK, proposal, 0, ("HOLD: no trade proposed",), None, config
        )
    if proposal.action is Action.SELL:
        return _evaluate_sell(proposal, account, config)
    return _evaluate_buy(proposal, account, config)
