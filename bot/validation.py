"""Structural validation of trade proposals.

Deterministic, explicit checks that a proposal is well-formed and internally
consistent. Agent output is treated as untrusted input: every field is
type-checked, nothing is coerced or "fixed", and all errors are collected so
each rejection is fully explained.

This is NOT risk management and NOT approval. A valid proposal is merely
well-formed; it is not approved for execution. Position sizing, exposure
limits, daily loss limits, and portfolio ownership checks (e.g. "do we hold
this ticker before a SELL?") are separate, later steps that decide approval.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from numbers import Real

from core.proposal import Action, TradeProposal
from core.symbols import MAX_TICKER_LENGTH, TICKER_PATTERN


@dataclass(frozen=True)
class ValidationResult:
    errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        """True if the proposal is structurally well-formed.

        Does NOT mean the trade is approved for execution. Approval is a
        separate decision made by the risk manager.
        """
        return not self.errors


def is_number(value) -> bool:
    # bool is a subclass of int; True/False are never valid numbers here.
    return isinstance(value, Real) and not isinstance(value, bool)


def _check_price(name: str, value, errors: list[str]) -> bool:
    """Append an error if value is not a finite positive number. Returns True if valid."""
    if not is_number(value):
        errors.append(f"{name} must be a number, got {type(value).__name__}")
        return False
    if not math.isfinite(value):
        errors.append(f"{name} must be finite")
        return False
    if value <= 0:
        errors.append(f"{name} must be positive")
        return False
    return True


def _validate_common(p: TradeProposal, errors: list[str]) -> None:
    if not isinstance(p.ticker, str):
        errors.append("ticker must be a string")
    elif len(p.ticker) > MAX_TICKER_LENGTH or not TICKER_PATTERN.fullmatch(p.ticker):
        errors.append(
            f"ticker {p.ticker!r} is malformed (expected uppercase symbol, "
            f"max {MAX_TICKER_LENGTH} chars, e.g. 'NVDA' or 'BRK.B')"
        )

    if not isinstance(p.action, Action):
        errors.append(f"action must be one of {[a.value for a in Action]}")

    if not is_number(p.confidence):
        errors.append("confidence must be a number")
    elif not math.isfinite(p.confidence) or not 0 <= p.confidence <= 1:
        errors.append("confidence must be between 0 and 1")

    if not isinstance(p.reasoning, str) or not p.reasoning.strip():
        errors.append("reasoning must be a non-empty string")

    if not isinstance(p.created_at, datetime):
        errors.append("created_at must be a datetime")
    elif p.created_at.tzinfo is None:
        errors.append("created_at must be timezone-aware")


def _validate_buy(p: TradeProposal, errors: list[str]) -> None:
    if p.entry is None:
        errors.append("BUY requires an entry price")
        entry_ok = False
    else:
        entry_ok = _check_price("entry", p.entry, errors)

    if p.stop_loss is None:
        errors.append("BUY requires a stop loss")
    elif _check_price("stop_loss", p.stop_loss, errors) and entry_ok:
        if p.stop_loss >= p.entry:
            errors.append("BUY stop loss must be below entry")

    if p.take_profit is not None:
        if _check_price("take_profit", p.take_profit, errors) and entry_ok:
            if p.take_profit <= p.entry:
                errors.append("BUY take profit must be above entry")


def _validate_sell(p: TradeProposal, errors: list[str]) -> None:
    # SELL closes an existing long position (no short selling in V1).
    if p.entry is not None:
        _check_price("entry (exit price)", p.entry, errors)
    if p.stop_loss is not None:
        errors.append("SELL closes a long position; stop loss must not be set")
    if p.take_profit is not None:
        errors.append("SELL closes a long position; take profit must not be set")


def _validate_hold(p: TradeProposal, errors: list[str]) -> None:
    for name in ("entry", "stop_loss", "take_profit"):
        if getattr(p, name) is not None:
            errors.append(f"HOLD must not set {name}")


_ACTION_VALIDATORS = {
    Action.BUY: _validate_buy,
    Action.SELL: _validate_sell,
    Action.HOLD: _validate_hold,
}


def validate_proposal(proposal) -> ValidationResult:
    """Return a ValidationResult listing every structural problem. Never raises."""
    if not isinstance(proposal, TradeProposal):
        return ValidationResult((f"expected TradeProposal, got {type(proposal).__name__}",))

    errors: list[str] = []
    _validate_common(proposal, errors)
    if isinstance(proposal.action, Action):
        _ACTION_VALIDATORS[proposal.action](proposal, errors)
    return ValidationResult(tuple(errors))
