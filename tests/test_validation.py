"""Tests for structural proposal validation (bot/validation.py)."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from bot.validation import ValidationResult, validate_proposal
from core.proposal import Action, TradeProposal

FIXED_TIME = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)


def buy(**overrides) -> TradeProposal:
    fields = dict(
        ticker="NVDA",
        action=Action.BUY,
        confidence=0.84,
        reasoning="Positive sentiment, bullish trend, and increasing volume.",
        entry=185.00,
        stop_loss=179.00,
        take_profit=197.00,
        created_at=FIXED_TIME,
    )
    return TradeProposal(**{**fields, **overrides})


def sell(**overrides) -> TradeProposal:
    fields = dict(
        ticker="NVDA",
        action=Action.SELL,
        confidence=0.70,
        reasoning="Target reached; momentum fading.",
        entry=196.50,
        created_at=FIXED_TIME,
    )
    return TradeProposal(**{**fields, **overrides})


def hold(**overrides) -> TradeProposal:
    fields = dict(
        ticker="NVDA",
        action=Action.HOLD,
        confidence=0.55,
        reasoning="Mixed signals; no clear edge.",
        created_at=FIXED_TIME,
    )
    return TradeProposal(**{**fields, **overrides})


def assert_rejected(proposal, *fragments: str) -> ValidationResult:
    result = validate_proposal(proposal)
    assert not result.is_valid
    joined = " | ".join(result.errors)
    for fragment in fragments:
        assert fragment in joined, f"expected {fragment!r} in errors: {joined}"
    return result


# --- Contract (core/proposal.py) ---------------------------------------------


def test_proposal_is_immutable():
    with pytest.raises(FrozenInstanceError):
        buy().stop_loss = 1.0


def test_created_at_defaults_to_aware_utc():
    p = TradeProposal(ticker="NVDA", action=Action.HOLD, confidence=0.5, reasoning="x")
    assert p.created_at.tzinfo is not None
    assert validate_proposal(p).is_valid


def test_action_values():
    assert {a.value for a in Action} == {"BUY", "SELL", "HOLD"}


# --- Valid examples ----------------------------------------------------------


@pytest.mark.parametrize(
    "proposal",
    [
        buy(),
        buy(take_profit=None),
        buy(entry=185, stop_loss=179, take_profit=197),  # ints are valid numbers
        sell(),
        sell(entry=None),  # exit at market
        hold(),
        buy(confidence=0.0),
        buy(confidence=1.0),
        buy(ticker="BRK.B"),
        buy(ticker="BF-B"),
        buy(ticker="A"),
    ],
)
def test_valid_proposals(proposal):
    result = validate_proposal(proposal)
    assert result.is_valid, result.errors
    assert result.errors == ()


# --- Input type --------------------------------------------------------------


@pytest.mark.parametrize("bad", [None, {}, "BUY NVDA", 42])
def test_non_proposal_input_rejected_without_raising(bad):
    assert_rejected(bad, "expected TradeProposal")


# --- Ticker ------------------------------------------------------------------


@pytest.mark.parametrize(
    "ticker",
    ["", "nvda", "Nvda", " NVDA", "NVDA ", "NV DA", "1NVDA", "NVDA.", ".B", "BRK..B",
     "TOOLONGTICKR", "NVDA;DROP", "$NVDA"],
)
def test_malformed_ticker_rejected(ticker):
    assert_rejected(buy(ticker=ticker), "ticker")


@pytest.mark.parametrize("ticker", [None, 123, ["NVDA"]])
def test_non_string_ticker_rejected(ticker):
    assert_rejected(buy(ticker=ticker), "ticker must be a string")


# --- Action ------------------------------------------------------------------


@pytest.mark.parametrize("action", ["BUY", "buy", "SHORT", None, 1])
def test_action_must_be_enum_member(action):
    # Raw strings are rejected: the agent boundary must produce a real Action.
    assert_rejected(buy(action=action), "action must be one of")


# --- Confidence --------------------------------------------------------------


@pytest.mark.parametrize("confidence", [-0.01, 1.01, 84, float("nan"), float("inf")])
def test_confidence_out_of_range_rejected(confidence):
    assert_rejected(buy(confidence=confidence), "confidence must be between 0 and 1")


@pytest.mark.parametrize("confidence", [None, "0.8", True])
def test_confidence_non_number_rejected(confidence):
    assert_rejected(buy(confidence=confidence), "confidence must be a number")


# --- Reasoning ---------------------------------------------------------------


@pytest.mark.parametrize("reasoning", ["", "   ", None, 5])
def test_reasoning_required(reasoning):
    assert_rejected(buy(reasoning=reasoning), "reasoning must be a non-empty string")


# --- Timestamp ---------------------------------------------------------------


def test_naive_timestamp_rejected():
    assert_rejected(buy(created_at=datetime(2026, 10, 3, 14, 30)), "timezone-aware")


def test_non_datetime_timestamp_rejected():
    assert_rejected(buy(created_at="2026-10-03"), "created_at must be a datetime")


# --- BUY ---------------------------------------------------------------------


def test_buy_requires_entry():
    assert_rejected(buy(entry=None), "BUY requires an entry price")


def test_buy_requires_stop_loss():
    assert_rejected(buy(stop_loss=None), "BUY requires a stop loss")


@pytest.mark.parametrize("stop_loss", [185.00, 190.00])
def test_buy_stop_loss_must_be_below_entry(stop_loss):
    assert_rejected(buy(stop_loss=stop_loss), "stop loss must be below entry")


@pytest.mark.parametrize("take_profit", [185.00, 180.00])
def test_buy_take_profit_must_be_above_entry(take_profit):
    assert_rejected(buy(take_profit=take_profit), "take profit must be above entry")


@pytest.mark.parametrize("field", ["entry", "stop_loss", "take_profit"])
@pytest.mark.parametrize(
    "value, message",
    [
        (0, "must be positive"),
        (-1.0, "must be positive"),
        (float("nan"), "must be finite"),
        (float("inf"), "must be finite"),
        ("185", "must be a number"),
        (True, "must be a number"),
    ],
)
def test_buy_bad_prices_rejected(field, value, message):
    assert_rejected(buy(**{field: value}), f"{field} {message}")


def test_bad_entry_skips_relative_price_checks():
    # Ordering checks need a valid entry; only the root cause is reported.
    result = assert_rejected(buy(entry=-5.0), "entry must be positive")
    assert len(result.errors) == 1


# --- SELL (close an existing long only) --------------------------------------


def test_sell_rejects_stop_loss():
    assert_rejected(sell(stop_loss=200.0), "SELL closes a long position; stop loss")


def test_sell_rejects_take_profit():
    assert_rejected(sell(take_profit=180.0), "SELL closes a long position; take profit")


def test_sell_short_style_proposal_rejected():
    # The shape of a short entry (stop above, target below) is not allowed in V1.
    assert_rejected(
        sell(entry=185.0, stop_loss=191.0, take_profit=173.0), "stop loss", "take profit"
    )


@pytest.mark.parametrize("entry", [0, -1.0, float("nan"), "196.50"])
def test_sell_bad_exit_price_rejected(entry):
    assert_rejected(sell(entry=entry), "entry (exit price)")


# --- HOLD --------------------------------------------------------------------


@pytest.mark.parametrize("field", ["entry", "stop_loss", "take_profit"])
def test_hold_rejects_prices(field):
    assert_rejected(hold(**{field: 100.0}), f"HOLD must not set {field}")


# --- Result behavior ---------------------------------------------------------


def test_all_errors_collected():
    p = buy(ticker="nvda", confidence=2.0, reasoning="", stop_loss=None)
    result = validate_proposal(p)
    assert len(result.errors) == 4


def test_validation_is_deterministic():
    p = buy(ticker="bad ticker", stop_loss=190.0)
    assert validate_proposal(p) == validate_proposal(p)


def test_validation_does_not_mutate_proposal():
    p = buy()
    snapshot = replace(p)
    validate_proposal(p)
    assert p == snapshot
