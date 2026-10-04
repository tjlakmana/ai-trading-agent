"""Tests for the deterministic risk manager (bot/risk.py)."""

import itertools
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from bot.risk import (
    Decision,
    RiskDecision,
    Stage,
    compute_equity,
    daily_loss_status,
    evaluate,
    floor_shares,
    size_buy,
    validate_account,
)
from bot.risk_config import RiskConfig
from core.portfolio import AccountState, Position
from core.proposal import Action, TradeProposal

T0 = datetime(2026, 10, 3, 14, 30, tzinfo=timezone.utc)
CONFIG = RiskConfig()  # 1% risk/trade, 20% max position, 3% max daily loss
TOL = 1e-9


def account(cash=100_000.0, positions=(), start_of_day_equity=None) -> AccountState:
    positions = tuple(positions)
    if start_of_day_equity is None:
        start_of_day_equity = cash + sum(p.quantity * p.market_price for p in positions)
    return AccountState(cash=cash, positions=positions, start_of_day_equity=start_of_day_equity)


def buy(entry=185.0, stop_loss=179.0, ticker="NVDA") -> TradeProposal:
    return TradeProposal(
        ticker=ticker, action=Action.BUY, confidence=0.84, reasoning="test buy",
        entry=entry, stop_loss=stop_loss, take_profit=None, created_at=T0,
    )


def sell(ticker="NVDA", entry=196.50) -> TradeProposal:
    return TradeProposal(
        ticker=ticker, action=Action.SELL, confidence=0.7, reasoning="test sell",
        entry=entry, created_at=T0,
    )


def hold(ticker="NVDA") -> TradeProposal:
    return TradeProposal(
        ticker=ticker, action=Action.HOLD, confidence=0.5, reasoning="test hold", created_at=T0,
    )


def reasons_text(decision: RiskDecision) -> str:
    return " | ".join(decision.reasons)


# --- Contract (core/portfolio.py) --------------------------------------------


def test_portfolio_types_are_immutable():
    with pytest.raises(FrozenInstanceError):
        Position("NVDA", 10, 185.0).quantity = 99
    with pytest.raises(FrozenInstanceError):
        account().cash = 1e9


# --- Equity ------------------------------------------------------------------


def test_equity_cash_only():
    assert compute_equity(account(cash=100_000.0)) == 100_000.0


def test_equity_values_positions_at_market_price():
    acct = account(cash=50_000.0, positions=[Position("NVDA", 100, 200.0), Position("AAPL", 10, 1_000.0)])
    assert compute_equity(acct) == 80_000.0


# --- Share rounding ----------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [(0.0, 0), (0.999, 0), (2.5, 2), (2.9999999999999996, 3), (9999.99999999999, 10_000), (166.67, 166)],
)
def test_floor_shares(raw, expected):
    assert floor_shares(raw) == expected


def test_floor_shares_never_negative():
    assert floor_shares(-5.0) == 0


# --- Account validation (fail closed) ----------------------------------------


def test_valid_account_has_no_errors():
    assert validate_account(account(positions=[Position("NVDA", 10, 185.0)])) == ()


def test_zero_cash_with_positions_is_valid():
    assert validate_account(account(cash=0.0, positions=[Position("AAPL", 10, 200.0)])) == ()


@pytest.mark.parametrize("bad", [None, {}, "account"])
def test_non_account_rejected(bad):
    assert "expected AccountState" in " ".join(validate_account(bad))


@pytest.mark.parametrize("cash", [-1.0, float("nan"), float("inf"), "100", True, None])
def test_bad_cash_rejected(cash):
    assert any("cash" in e for e in validate_account(account(cash=cash, start_of_day_equity=100.0)))


@pytest.mark.parametrize("sod", [0, -1.0, float("nan"), float("inf"), "100", None])
def test_bad_start_of_day_equity_rejected(sod):
    acct = AccountState(cash=100_000.0, positions=(), start_of_day_equity=sod)
    assert any("start_of_day_equity" in e for e in validate_account(acct))


def test_positions_must_be_tuple():
    acct = AccountState(cash=100.0, positions=[Position("NVDA", 1, 10.0)], start_of_day_equity=110.0)
    assert any("positions" in e for e in validate_account(acct))


def test_position_entries_must_be_positions():
    acct = AccountState(cash=100.0, positions=({"ticker": "NVDA"},), start_of_day_equity=100.0)
    assert any("Position" in e for e in validate_account(acct))


@pytest.mark.parametrize("quantity", [0, -5, 1.5, True, "10", None])
def test_bad_position_quantity_rejected(quantity):
    acct = AccountState(cash=100.0, positions=(Position("NVDA", quantity, 10.0),), start_of_day_equity=100.0)
    assert any("quantity" in e for e in validate_account(acct))


@pytest.mark.parametrize("price", [0, -1.0, float("nan"), float("inf"), "10", None])
def test_bad_position_price_rejected(price):
    acct = AccountState(cash=100.0, positions=(Position("NVDA", 1, price),), start_of_day_equity=100.0)
    assert any("market_price" in e for e in validate_account(acct))


@pytest.mark.parametrize("ticker", ["nvda", "", None, "NV DA"])
def test_bad_position_ticker_rejected(ticker):
    acct = AccountState(cash=100.0, positions=(Position(ticker, 1, 10.0),), start_of_day_equity=110.0)
    assert any("ticker" in e for e in validate_account(acct))


def test_duplicate_position_tickers_rejected():
    acct = account(positions=[Position("NVDA", 1, 10.0), Position("NVDA", 2, 10.0)])
    assert any("duplicate" in e for e in validate_account(acct))


def test_non_positive_equity_rejected():
    acct = AccountState(cash=0.0, positions=(), start_of_day_equity=100.0)
    assert any("equity" in e for e in validate_account(acct))


# --- Daily loss status -------------------------------------------------------


def test_account_below_start_of_day_equity():
    s = daily_loss_status(account(cash=99_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert s.daily_loss == 1_000.0
    assert s.daily_loss_limit == 3_000.0
    assert s.remaining_daily_loss == 2_000.0
    assert not s.limit_reached


def test_account_exactly_at_start_of_day_equity():
    s = daily_loss_status(account(cash=100_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert s.daily_loss == 0.0
    assert s.remaining_daily_loss == 3_000.0
    assert not s.limit_reached


def test_account_above_start_of_day_equity():
    # Profits do not create a negative loss and do not enlarge the allowance.
    s = daily_loss_status(account(cash=105_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert s.daily_loss == 0.0
    assert s.daily_loss_limit == 3_000.0  # based on start-of-day equity, not current
    assert s.remaining_daily_loss == 3_000.0
    assert not s.limit_reached


def test_exactly_at_daily_loss_limit():
    s = daily_loss_status(account(cash=97_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert s.daily_loss == 3_000.0
    assert s.remaining_daily_loss == 0.0
    assert s.limit_reached


def test_beyond_daily_loss_limit():
    s = daily_loss_status(account(cash=96_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert s.daily_loss == 4_000.0
    assert s.remaining_daily_loss == 0.0
    assert s.limit_reached


# --- Daily loss in evaluation ------------------------------------------------


def test_buy_rejected_exactly_at_daily_loss_limit():
    d = evaluate(buy(50.0, 45.0), account(cash=97_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.stage is Stage.RISK
    assert d.quantity == 0
    assert "daily loss limit reached" in reasons_text(d)
    assert d.sizing is not None  # numbers still recorded for audit


def test_buy_rejected_beyond_daily_loss_limit():
    d = evaluate(buy(50.0, 45.0), account(cash=96_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert d.decision is Decision.REJECT
    assert "daily loss limit reached" in reasons_text(d)


def test_buy_allowed_below_daily_loss_limit():
    d = evaluate(buy(50.0, 45.0), account(cash=99_000.0, start_of_day_equity=100_000.0), CONFIG)
    assert d.decision is Decision.APPROVE


def test_remaining_daily_allowance_caps_risk_budget():
    # Down $2,500: allowance $500 < per-trade budget $975 (1% of $97,500).
    d = evaluate(buy(50.0, 45.0), account(cash=97_500.0, start_of_day_equity=100_000.0), CONFIG)
    assert d.decision is Decision.APPROVE
    assert d.sizing.risk_budget == 500.0
    assert d.sizing.qty_by_risk == 100
    assert d.quantity == 100
    assert d.sizing.binding_constraint == "daily_loss"


def test_profitable_day_does_not_increase_risk_budget():
    # Per-trade limit 5% would allow $5,250 at $105k equity. The daily allowance
    # stays $3,000 (3% of start-of-day) because profits do not add to it.
    config = RiskConfig(max_risk_per_trade_pct=0.05)
    d = evaluate(buy(50.0, 40.0), account(cash=105_000.0, start_of_day_equity=100_000.0), config)
    assert d.sizing.daily_loss == 0.0
    assert d.sizing.remaining_daily_loss == 3_000.0
    assert d.sizing.risk_budget == 3_000.0
    assert d.quantity == 300
    assert d.sizing.binding_constraint == "daily_loss"


# --- Per-trade risk basis: min(current equity, start-of-day equity) ---------


def test_intraday_profit_does_not_increase_per_trade_risk():
    # Up $5,000: 1% of current equity would be $1,050; basis stays $100,000.
    d = evaluate(buy(50.0, 45.0), account(cash=105_000.0, start_of_day_equity=100_000.0), CONFIG)
    s = d.sizing
    assert s.equity == 105_000.0
    assert s.risk_basis == 100_000.0
    assert s.per_trade_risk_limit == 1_000.0
    assert s.risk_budget == 1_000.0
    assert d.quantity == 200
    assert s.binding_constraint == "risk"


def test_intraday_loss_reduces_per_trade_risk():
    # Down $1,000: basis is current equity $99,000, so the limit drops to $990.
    d = evaluate(buy(50.0, 45.0), account(cash=99_000.0, start_of_day_equity=100_000.0), CONFIG)
    s = d.sizing
    assert s.risk_basis == 99_000.0
    assert s.per_trade_risk_limit == 990.0
    assert s.remaining_daily_loss == 2_000.0  # allowance is not the binding cap here
    assert s.risk_budget == 990.0
    assert d.quantity == 198
    assert s.binding_constraint == "risk"


def test_daily_allowance_reduces_budget_below_per_trade_limit():
    # Down $2,500: per-trade limit $975 (1% of $97,500), allowance only $500.
    d = evaluate(buy(50.0, 45.0), account(cash=97_500.0, start_of_day_equity=100_000.0), CONFIG)
    s = d.sizing
    assert s.per_trade_risk_limit == 975.0
    assert s.remaining_daily_loss == 500.0
    assert s.risk_budget == 500.0
    assert s.binding_constraint == "daily_loss"


def test_flat_day_risk_basis_equals_equity():
    s = evaluate(buy(50.0, 45.0), account(), CONFIG).sizing
    assert s.risk_basis == s.equity == 100_000.0
    assert s.per_trade_risk_limit == 1_000.0


def test_sell_allowed_when_daily_loss_limit_reached():
    acct = account(cash=50_000.0, positions=[Position("NVDA", 100, 400.0)], start_of_day_equity=110_000.0)
    assert daily_loss_status(acct, CONFIG).limit_reached
    d = evaluate(sell("NVDA"), acct, CONFIG)
    assert d.decision is Decision.APPROVE
    assert d.quantity == 100


# --- BUY sizing: each limit binding ------------------------------------------


def test_size_limited_by_risk():
    d = evaluate(buy(50.0, 45.0), account(), CONFIG)
    s = d.sizing
    assert (s.qty_by_risk, s.qty_by_exposure, s.qty_by_cash) == (200, 400, 2_000)
    assert d.decision is Decision.APPROVE
    assert d.quantity == 200
    assert s.binding_constraint == "risk"
    assert s.stop_distance == 5.0
    assert s.planned_risk == 1_000.0
    assert s.position_value == 10_000.0


def test_size_limited_by_exposure():
    d = evaluate(buy(185.0, 179.0), account(), CONFIG)
    s = d.sizing
    assert (s.qty_by_risk, s.qty_by_exposure, s.qty_by_cash) == (166, 108, 540)
    assert d.quantity == 108
    assert s.binding_constraint == "exposure"
    assert s.planned_risk == 648.0  # below the $1,000 budget: exposure was stricter


def test_size_limited_by_cash():
    acct = account(cash=5_000.0, positions=[Position("AAPL", 475, 200.0)])  # equity $100k
    d = evaluate(buy(50.0, 45.0), acct, CONFIG)
    s = d.sizing
    assert (s.qty_by_risk, s.qty_by_exposure, s.qty_by_cash) == (200, 400, 100)
    assert d.quantity == 100
    assert s.binding_constraint == "cash"


def test_tight_stop_is_capped_by_exposure():
    d = evaluate(buy(100.0, 99.99), account(), CONFIG)
    assert d.sizing.qty_by_risk > 10_000
    assert d.quantity == 200
    assert d.sizing.binding_constraint == "exposure"


def test_float_boundary_rounds_to_intended_whole_shares():
    # 1.3 - 1.2 == 0.10000000000000009 in floating point; $1,000 / $0.10 = 10,000 shares.
    d = evaluate(buy(1.3, 1.2), account(), CONFIG)
    assert d.sizing.qty_by_risk == 10_000
    assert d.quantity == 10_000


def test_size_buy_matches_evaluate():
    acct = account()
    assert size_buy(buy(), acct, CONFIG) == evaluate(buy(), acct, CONFIG).sizing


# --- BUY: existing positions and exposure ------------------------------------


def test_adding_to_existing_position_uses_remaining_room():
    acct = account(cash=90_750.0, positions=[Position("NVDA", 50, 185.0)])  # $9,250 held, equity $100k
    d = evaluate(buy(185.0, 179.0), acct, CONFIG)
    assert d.sizing.existing_position_value == 9_250.0
    assert d.sizing.qty_by_exposure == 58  # (20,000 - 9,250) / 185
    assert d.quantity == 58


def test_existing_position_at_cap_rejected():
    acct = account(cash=80_000.0, positions=[Position("NVDA", 100, 200.0)])  # exactly 20%
    d = evaluate(buy(185.0, 179.0), acct, CONFIG)
    assert d.decision is Decision.REJECT
    assert d.sizing.qty_by_exposure == 0
    assert "exposure" in reasons_text(d)


def test_existing_position_above_cap_rejected():
    acct = account(cash=70_000.0, positions=[Position("NVDA", 150, 200.0)])  # 30%
    d = evaluate(buy(185.0, 179.0), acct, CONFIG)
    assert d.decision is Decision.REJECT
    assert d.sizing.qty_by_exposure == 0


def test_existing_value_uses_market_price_not_proposed_entry():
    # Held at market $200 = $20,000 (at cap). Valuing at the proposed $185 would wrongly leave room.
    acct = account(cash=80_000.0, positions=[Position("NVDA", 100, 200.0)])
    d = evaluate(buy(185.0, 179.0), acct, CONFIG)
    assert d.sizing.existing_position_value == 20_000.0
    assert d.decision is Decision.REJECT


def test_other_ticker_positions_do_not_count_toward_exposure():
    acct = account(cash=70_000.0, positions=[Position("AAPL", 150, 200.0)])
    d = evaluate(buy(185.0, 179.0), acct, CONFIG)
    assert d.sizing.existing_position_value == 0.0
    assert d.quantity == 108


# --- BUY: zero-quantity rejections -------------------------------------------


def test_stop_distance_larger_than_risk_budget_rejected():
    d = evaluate(buy(3_000.0, 1_900.0), account(), CONFIG)  # $1,100/share > $1,000 budget
    assert d.decision is Decision.REJECT
    assert d.quantity == 0
    assert d.sizing.qty_by_risk == 0
    assert "risk" in reasons_text(d)


def test_share_price_above_exposure_room_rejected():
    d = evaluate(buy(25_000.0, 24_990.0), account(), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.sizing.qty_by_exposure == 0
    assert "exposure" in reasons_text(d)


def test_no_cash_rejected():
    acct = account(cash=0.0, positions=[Position("AAPL", 500, 200.0)])
    d = evaluate(buy(50.0, 45.0), acct, CONFIG)
    assert d.decision is Decision.REJECT
    assert d.sizing.qty_by_cash == 0
    assert "cash" in reasons_text(d)


def test_all_blocking_limits_reported():
    acct = account(cash=1_000.0, positions=[Position("AAPL", 495, 200.0)])  # equity $100k
    d = evaluate(buy(30_000.0, 20_000.0), acct, CONFIG)
    assert d.decision is Decision.REJECT
    assert len(d.reasons) == 3
    for word in ("risk", "exposure", "cash"):
        assert word in reasons_text(d)


# --- BUY: invariants over a grid of inputs -----------------------------------


@pytest.mark.parametrize(
    "cash, entry, stop",
    list(itertools.product([0.0, 1_000.0, 25_000.0, 100_000.0], [0.5, 7.77, 50.0, 185.0, 999.0],
                           [0.01, 0.10, 0.3333, 0.75])),
)
def test_sizing_never_exceeds_any_limit(cash, entry, stop):
    stop_loss = entry * (1 - stop)
    acct = account(cash=cash, positions=[Position("AAPL", 100, 500.0)])
    d = evaluate(buy(entry, stop_loss), acct, CONFIG)
    s = d.sizing
    equity = compute_equity(acct)
    assert d.quantity >= 0
    assert s.planned_risk <= s.risk_budget * (1 + TOL)
    assert s.position_value <= equity * CONFIG.max_position_pct * (1 + TOL)
    assert s.position_value <= cash * (1 + TOL)
    assert (d.decision is Decision.APPROVE) == (d.quantity >= 1)


# --- SELL --------------------------------------------------------------------


def test_sell_closes_entire_existing_position():
    acct = account(cash=80_000.0, positions=[Position("NVDA", 108, 185.0)])
    d = evaluate(sell("NVDA"), acct, CONFIG)
    assert d.decision is Decision.APPROVE
    assert d.stage is Stage.RISK
    assert d.quantity == 108
    assert d.sizing is None


def test_sell_at_market_approved():
    acct = account(positions=[Position("NVDA", 5, 185.0)])
    assert evaluate(sell("NVDA", entry=None), acct, CONFIG).quantity == 5


def test_sell_without_position_rejected():
    d = evaluate(sell("NVDA"), account(), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.quantity == 0
    assert "no long position in NVDA" in reasons_text(d)


def test_sell_with_only_other_tickers_rejected():
    acct = account(positions=[Position("AAPL", 10, 200.0)])
    assert evaluate(sell("NVDA"), acct, CONFIG).decision is Decision.REJECT


def test_sell_ticker_match_is_exact():
    acct = account(positions=[Position("BRK-B", 10, 400.0)])
    assert evaluate(sell("BRK.B"), acct, CONFIG).decision is Decision.REJECT


# --- HOLD --------------------------------------------------------------------


def test_hold_returns_no_action():
    d = evaluate(hold(), account(), CONFIG)
    assert d.decision is Decision.NO_ACTION
    assert d.stage is Stage.RISK
    assert d.quantity == 0
    assert d.sizing is None
    assert not d.is_approved


def test_hold_is_never_approved_even_with_position():
    d = evaluate(hold("NVDA"), account(positions=[Position("NVDA", 10, 185.0)]), CONFIG)
    assert d.decision is Decision.NO_ACTION


# --- Pipeline ----------------------------------------------------------------


def test_invalid_proposal_rejected_at_validation_stage():
    bad = replace(buy(), stop_loss=190.0)  # stop above entry
    d = evaluate(bad, account(), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.stage is Stage.VALIDATION
    assert d.quantity == 0
    assert d.sizing is None
    assert "stop loss must be below entry" in reasons_text(d)


@pytest.mark.parametrize("bad", [None, {"ticker": "NVDA"}, "BUY NVDA"])
def test_non_proposal_rejected_at_validation_stage(bad):
    d = evaluate(bad, account(), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.stage is Stage.VALIDATION
    assert d.proposal is None


def test_invalid_account_rejected_at_account_stage():
    d = evaluate(buy(), account(cash=-1.0, start_of_day_equity=100.0), CONFIG)
    assert d.decision is Decision.REJECT
    assert d.stage is Stage.ACCOUNT
    assert d.sizing is None
    assert "cash" in reasons_text(d)


def test_validation_runs_before_account_checks():
    d = evaluate(replace(buy(), ticker="bad"), account(cash=-1.0, start_of_day_equity=100.0), CONFIG)
    assert d.stage is Stage.VALIDATION


@pytest.mark.parametrize("bad_config", [None, {"max_position_pct": 1.0}, 0.01])
def test_config_must_be_risk_config(bad_config):
    with pytest.raises(TypeError):
        evaluate(buy(), account(), bad_config)


def test_decision_records_config_used():
    config = RiskConfig(max_position_pct=0.5)
    assert evaluate(buy(), account(), config).config is config


# --- Principles --------------------------------------------------------------


def test_confidence_does_not_affect_size_or_approval():
    low = evaluate(replace(buy(), confidence=0.01), account(), CONFIG)
    high = evaluate(replace(buy(), confidence=0.99), account(), CONFIG)
    assert low.decision == high.decision
    assert low.quantity == high.quantity
    assert low.sizing == high.sizing


def test_evaluation_is_deterministic():
    acct = account(cash=97_500.0, positions=[Position("NVDA", 10, 185.0)], start_of_day_equity=100_000.0)
    assert evaluate(buy(), acct, CONFIG) == evaluate(buy(), acct, CONFIG)


def test_evaluation_does_not_mutate_inputs():
    proposal, acct, config = buy(), account(positions=[Position("NVDA", 10, 185.0)]), RiskConfig()
    snapshot = (replace(proposal), replace(acct), replace(config))
    evaluate(proposal, acct, config)
    assert (proposal, acct, config) == snapshot


def test_risk_decision_is_immutable():
    d = evaluate(buy(), account(), CONFIG)
    with pytest.raises(FrozenInstanceError):
        d.quantity = 10_000


def test_only_approve_is_approved():
    assert evaluate(buy(), account(), CONFIG).is_approved
    assert not evaluate(sell(), account(), CONFIG).is_approved
    assert not evaluate(hold(), account(), CONFIG).is_approved


@pytest.mark.parametrize(
    "decision, quantity",
    [(Decision.APPROVE, 0), (Decision.REJECT, 5), (Decision.NO_ACTION, 1), (Decision.APPROVE, -1)],
)
def test_risk_decision_quantity_invariant(decision, quantity):
    # APPROVE must carry >= 1 share; REJECT and NO_ACTION must carry 0.
    with pytest.raises(ValueError):
        RiskDecision(decision=decision, stage=Stage.RISK, proposal=buy(), quantity=quantity,
                     reasons=("x",), sizing=None, config=CONFIG)
