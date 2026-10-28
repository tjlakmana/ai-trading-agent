"""Tests for the deterministic in-play filter (strategy/in_play.py)."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from core.market import Catalyst, CatalystType, ScannerSnapshot
from strategy.in_play import (
    CheckStatus,
    compute_metrics,
    evaluate_in_play,
    evaluate_universe,
    validate_snapshot,
)
from strategy.in_play_config import InPlayConfig, Level

T0 = datetime(2026, 10, 5, 13, 45, tzinfo=timezone.utc)  # 9:45 ET
CONFIG = InPlayConfig()
FDA = Catalyst(present=True, type=CatalystType.FDA, headline="FDA approval", source="fixture")


def snap(**overrides) -> ScannerSnapshot:
    """An ideal V1 candidate: passes every HARD and PREFERRED check."""
    fields = dict(
        ticker="ABCD", as_of=T0, source="fixture",
        price=6.50, previous_close=5.00, open_price=6.00,
        cumulative_volume=4_000_000, average_daily_volume=500_000.0, premarket_volume=1_200_000,
        float_shares=6_000_000, catalyst=FDA,
        daily_resistance=9.00, resistance_checked=True,
    )
    return ScannerSnapshot(**{**fields, **overrides})


def at_price(price: float, **overrides) -> ScannerSnapshot:
    """Snapshot at a given price, still up 30% on the day."""
    return snap(price=price, previous_close=price / 1.3, daily_resistance=price * 2, **overrides)


def check(result, name):
    matches = [c for c in result.hard_checks + result.quality_checks if c.name == name]
    assert len(matches) == 1, f"expected exactly one {name!r} check"
    return matches[0]


def check_names(result):
    return {c.name for c in result.hard_checks + result.quality_checks}


# --- Metrics -----------------------------------------------------------------


def test_metrics_for_ideal_candidate():
    m = compute_metrics(snap())
    assert m.pct_change == pytest.approx(0.30)
    assert m.gap_pct == pytest.approx(0.20)
    assert m.volume_vs_avg_daily == pytest.approx(8.0)
    assert m.room_to_resistance_pct == pytest.approx((9.00 - 6.50) / 6.50)


def test_gap_is_none_before_open():
    assert compute_metrics(snap(open_price=None)).gap_pct is None


@pytest.mark.parametrize("avg", [None, 0.0])
def test_volume_ratio_none_without_usable_average(avg):
    assert compute_metrics(snap(average_daily_volume=avg)).volume_vs_avg_daily is None


def test_room_none_when_resistance_unknown():
    assert compute_metrics(snap(daily_resistance=None, resistance_checked=False)).room_to_resistance_pct is None


def test_room_none_when_no_overhead_resistance():
    assert compute_metrics(snap(daily_resistance=None, resistance_checked=True)).room_to_resistance_pct is None


def test_room_negative_when_resistance_below_price():
    assert compute_metrics(snap(daily_resistance=6.00)).room_to_resistance_pct < 0


def test_negative_pct_change():
    assert compute_metrics(snap(price=4.00)).pct_change == pytest.approx(-0.20)


# --- Snapshot validation (bad data is rejected, never raises) ----------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"ticker": "abcd"}, {"ticker": ""}, {"ticker": None},
        {"as_of": datetime(2026, 10, 5, 9, 45)}, {"as_of": "2026-10-05"},
        {"source": ""}, {"source": None},
        {"price": 0}, {"price": -1.0}, {"price": float("nan")}, {"price": "6.5"}, {"price": True},
        {"previous_close": 0}, {"previous_close": float("inf")},
        {"open_price": 0}, {"open_price": -6.0},
        {"cumulative_volume": -1}, {"cumulative_volume": 1.5}, {"cumulative_volume": True},
        {"average_daily_volume": -1.0}, {"average_daily_volume": float("nan")},
        {"premarket_volume": -1}, {"premarket_volume": 2.5},
        {"float_shares": 0}, {"float_shares": 6_000_000.0}, {"float_shares": True},
        {"catalyst": "FDA"},
        {"catalyst": Catalyst(present="yes", type=None, headline=None, source="x")},
        {"catalyst": Catalyst(present=True, type="FDA", headline=None, source="x")},
        {"catalyst": Catalyst(present=True, type=None, headline=None, source="")},
        {"daily_resistance": 0}, {"daily_resistance": -9.0},
        {"resistance_checked": "yes"},
        {"daily_resistance": 9.0, "resistance_checked": False},  # inconsistent
    ],
)
def test_invalid_snapshot_not_qualified(overrides):
    s = snap(**overrides)
    assert validate_snapshot(s) != ()
    r = evaluate_in_play(s, CONFIG)
    assert not r.qualified
    assert not r.valid_data
    assert r.metrics is None
    assert r.reasons
    assert r.snapshot is s  # raw input still preserved


@pytest.mark.parametrize("bad", [None, {"ticker": "ABCD"}, "ABCD"])
def test_non_snapshot_input_not_qualified(bad):
    r = evaluate_in_play(bad, CONFIG)
    assert not r.qualified and not r.valid_data
    assert r.snapshot is None
    assert r.ticker is None


def test_valid_snapshot_has_no_errors():
    assert validate_snapshot(snap()) == ()


def test_optional_fields_may_be_none():
    s = snap(open_price=None, average_daily_volume=None, premarket_volume=None,
             float_shares=None, catalyst=None, daily_resistance=None, resistance_checked=False)
    assert validate_snapshot(s) == ()


def test_config_must_be_in_play_config():
    with pytest.raises(TypeError):
        evaluate_in_play(snap(), {"min_price": 2.0})


# --- Ideal candidate ---------------------------------------------------------


def test_ideal_candidate_qualifies_cleanly():
    r = evaluate_in_play(snap(), CONFIG)
    assert r.qualified
    assert r.valid_data
    assert r.reasons == ()
    assert r.warnings == ()
    assert (r.quality_passed, r.quality_total) == (4, 4)
    assert all(c.status is CheckStatus.PASS for c in r.hard_checks + r.quality_checks)
    assert r.ticker == "ABCD"
    assert r.as_of == T0


def test_default_check_categories():
    r = evaluate_in_play(snap(), CONFIG)
    assert {c.name for c in r.hard_checks} == {
        "min_price", "max_price", "min_pct_change", "min_volume_vs_avg_daily", "max_float_shares",
    }
    assert {c.name for c in r.quality_checks} == {
        "preferred_max_float_shares", "preferred_volume_vs_avg_daily", "catalyst", "room_to_resistance",
    }
    assert all(c.level is Level.HARD for c in r.hard_checks)
    assert all(c.level is Level.PREFERRED for c in r.quality_checks)


# --- HARD: price range -------------------------------------------------------


@pytest.mark.parametrize("price, ok", [(1.99, False), (2.00, True), (20.00, True), (20.01, False)])
def test_price_range_boundaries(price, ok):
    r = evaluate_in_play(at_price(price), CONFIG)
    assert r.qualified is ok
    if not ok:
        assert any("price" in reason for reason in r.reasons)


# --- HARD: percent change ----------------------------------------------------


@pytest.mark.parametrize("price, ok", [(5.50, True), (5.49, False)])
def test_pct_change_boundary(price, ok):
    assert evaluate_in_play(snap(price=price, previous_close=5.00), CONFIG).qualified is ok


def test_pct_change_float_noise_at_boundary():
    # (3.3 - 3.0) / 3.0 == 0.09999999999999995 in floating point; intended +10%.
    assert evaluate_in_play(snap(price=3.3, previous_close=3.0, daily_resistance=5.0), CONFIG).qualified


def test_stock_down_on_day_fails():
    r = evaluate_in_play(snap(price=4.00), CONFIG)
    assert not r.qualified
    assert check(r, "min_pct_change").status is CheckStatus.FAIL


# --- HARD: volume vs average daily -------------------------------------------


@pytest.mark.parametrize("volume, ok", [(1_500_000, True), (1_499_999, False)])
def test_volume_vs_avg_daily_boundary(volume, ok):
    assert evaluate_in_play(snap(cumulative_volume=volume), CONFIG).qualified is ok


@pytest.mark.parametrize("avg", [None, 0.0])
def test_missing_average_volume_fails_closed(avg):
    r = evaluate_in_play(snap(average_daily_volume=avg), CONFIG)
    assert not r.qualified
    assert check(r, "min_volume_vs_avg_daily").status is CheckStatus.UNKNOWN
    assert any("unknown" in reason for reason in r.reasons)


# --- HARD (optional): minimum cumulative volume by session -------------------

VOLUME_CONFIG = InPlayConfig(min_cumulative_volume=500_000, min_premarket_cumulative_volume=100_000)


def test_session_volume_checks_absent_by_default():
    names = check_names(evaluate_in_play(snap(), CONFIG)) | check_names(
        evaluate_in_play(snap(open_price=None), CONFIG))
    assert "min_cumulative_volume" not in names
    assert "min_premarket_cumulative_volume" not in names


@pytest.mark.parametrize("volume, ok", [(500_000, True), (499_999, False)])
def test_regular_session_volume_boundary(volume, ok):
    r = evaluate_in_play(snap(cumulative_volume=volume, average_daily_volume=50_000.0), VOLUME_CONFIG)
    assert r.qualified is ok
    c = check(r, "min_cumulative_volume")
    assert c.level is Level.HARD
    assert c.status is (CheckStatus.PASS if ok else CheckStatus.FAIL)
    assert (c.actual, c.threshold) == (volume, 500_000)


@pytest.mark.parametrize("volume, ok", [(100_000, True), (99_999, False)])
def test_premarket_volume_boundary(volume, ok):
    s = snap(open_price=None, cumulative_volume=volume, average_daily_volume=10_000.0)
    r = evaluate_in_play(s, VOLUME_CONFIG)
    assert r.qualified is ok
    assert check(r, "min_premarket_cumulative_volume").status is (CheckStatus.PASS if ok else CheckStatus.FAIL)


def test_only_the_matching_session_threshold_applies():
    regular = check_names(evaluate_in_play(snap(), VOLUME_CONFIG))
    premarket = check_names(evaluate_in_play(snap(open_price=None), VOLUME_CONFIG))
    assert "min_cumulative_volume" in regular and "min_premarket_cumulative_volume" not in regular
    assert "min_premarket_cumulative_volume" in premarket and "min_cumulative_volume" not in premarket


def test_premarket_threshold_alone_leaves_regular_session_unchecked():
    config = InPlayConfig(min_premarket_cumulative_volume=100_000)
    assert "min_cumulative_volume" not in check_names(evaluate_in_play(snap(), config))


def test_session_volume_failure_message():
    r = evaluate_in_play(snap(cumulative_volume=400_000, average_daily_volume=40_000.0), VOLUME_CONFIG)
    assert "session volume 400,000 < min 500,000" in r.reasons


# --- HARD: float -------------------------------------------------------------


@pytest.mark.parametrize("float_shares, ok", [(20_000_000, True), (20_000_001, False)])
def test_float_boundary(float_shares, ok):
    assert evaluate_in_play(snap(float_shares=float_shares), CONFIG).qualified is ok


def test_unknown_float_fails_closed():
    r = evaluate_in_play(snap(float_shares=None), CONFIG)
    assert not r.qualified
    assert check(r, "max_float_shares").status is CheckStatus.UNKNOWN
    assert check(r, "preferred_max_float_shares").status is CheckStatus.UNKNOWN


def test_float_check_records_actual_and_threshold():
    c = check(evaluate_in_play(snap(float_shares=34_200_000), CONFIG), "max_float_shares")
    assert c.status is CheckStatus.FAIL
    assert c.actual == 34_200_000
    assert c.threshold == 20_000_000
    assert "34,200,000" in c.message and "20,000,000" in c.message


# --- HARD: all checks evaluated, none short-circuited ------------------------


def test_every_check_runs_after_a_hard_failure():
    r = evaluate_in_play(snap(price=25.00, previous_close=24.00, float_shares=50_000_000), CONFIG)
    assert not r.qualified
    assert check_names(r) == check_names(evaluate_in_play(snap(), CONFIG))
    assert len(r.reasons) == 3  # max_price, min_pct_change, max_float_shares


def test_disabled_threshold_is_not_checked():
    config = InPlayConfig(max_float_shares=None, preferred_max_float_shares=None)
    r = evaluate_in_play(snap(float_shares=None), config)
    assert r.qualified
    assert "max_float_shares" not in check_names(r)
    assert "preferred_max_float_shares" not in check_names(r)


# --- PREFERRED: failures warn but do not disqualify --------------------------


def test_float_above_preferred_warns():
    r = evaluate_in_play(snap(float_shares=15_000_000), CONFIG)
    assert r.qualified
    assert check(r, "preferred_max_float_shares").status is CheckStatus.FAIL
    assert (r.quality_passed, r.quality_total) == (3, 4)
    assert any("float" in w for w in r.warnings)


def test_volume_below_preferred_warns():
    r = evaluate_in_play(snap(cumulative_volume=2_000_000), CONFIG)  # 4x
    assert r.qualified
    assert check(r, "preferred_volume_vs_avg_daily").status is CheckStatus.FAIL
    assert r.warnings


def test_missing_catalyst_information_warns():
    r = evaluate_in_play(snap(catalyst=None), CONFIG)
    assert r.qualified
    assert check(r, "catalyst").status is CheckStatus.UNKNOWN
    assert any("catalyst" in w and "unknown" in w for w in r.warnings)


def test_no_catalyst_warns():
    r = evaluate_in_play(snap(catalyst=Catalyst(False, None, None, "fixture")), CONFIG)
    assert r.qualified
    assert check(r, "catalyst").status is CheckStatus.FAIL


def test_negative_catalyst_warns_but_counts_as_present():
    offering = Catalyst(True, CatalystType.OFFERING, "Priced $5M offering", "fixture")
    r = evaluate_in_play(snap(catalyst=offering), CONFIG)
    assert r.qualified
    assert check(r, "catalyst").status is CheckStatus.PASS
    assert any("OFFERING" in w for w in r.warnings)


def test_insufficient_room_warns():
    r = evaluate_in_play(snap(daily_resistance=7.00), CONFIG)  # ~7.7% room
    assert r.qualified
    c = check(r, "room_to_resistance")
    assert c.status is CheckStatus.FAIL
    assert c.threshold == 0.20


def test_resistance_at_price_fails_room():
    r = evaluate_in_play(snap(daily_resistance=6.50), CONFIG)
    assert check(r, "room_to_resistance").status is CheckStatus.FAIL


def test_unknown_resistance_warns():
    r = evaluate_in_play(snap(daily_resistance=None, resistance_checked=False), CONFIG)
    assert r.qualified
    assert check(r, "room_to_resistance").status is CheckStatus.UNKNOWN


def test_no_known_overhead_resistance_passes_room():
    r = evaluate_in_play(snap(daily_resistance=None, resistance_checked=True), CONFIG)
    c = check(r, "room_to_resistance")
    assert c.status is CheckStatus.PASS
    assert "no known overhead resistance" in c.message
    assert r.metrics.room_to_resistance_pct is None
    assert r.warnings == ()


def test_room_boundary_with_float_noise():
    # Exactly 20% room: resistance 7.80 over price 6.50.
    assert check(evaluate_in_play(snap(daily_resistance=7.80), CONFIG), "room_to_resistance").status \
        is CheckStatus.PASS


# --- Levels: category is configuration, not code -----------------------------


def test_catalyst_promoted_to_hard_changes_qualification():
    s = snap(catalyst=None)
    preferred = evaluate_in_play(s, InPlayConfig(catalyst_level=Level.PREFERRED))
    hard = evaluate_in_play(s, InPlayConfig(catalyst_level=Level.HARD))
    assert preferred.qualified and not hard.qualified
    assert check(hard, "catalyst").level is Level.HARD
    assert any("catalyst" in reason for reason in hard.reasons)
    assert preferred.metrics == hard.metrics  # same measurements, different policy


def test_hard_catalyst_passes_when_present():
    assert evaluate_in_play(snap(), InPlayConfig(catalyst_level=Level.HARD)).qualified


def test_room_promoted_to_hard_changes_qualification():
    s = snap(daily_resistance=7.00)
    assert evaluate_in_play(s, CONFIG).qualified
    assert not evaluate_in_play(s, InPlayConfig(room_level=Level.HARD)).qualified


def test_preferred_float_promoted_to_hard_via_threshold():
    s = snap(float_shares=15_000_000)
    assert evaluate_in_play(s, CONFIG).qualified
    assert not evaluate_in_play(s, InPlayConfig(max_float_shares=10_000_000)).qualified


def test_off_criteria_not_evaluated_but_raw_data_preserved():
    s = snap(catalyst=None, daily_resistance=None, resistance_checked=False)
    r = evaluate_in_play(s, InPlayConfig(catalyst_level=Level.OFF, room_level=Level.OFF))
    assert "catalyst" not in check_names(r)
    assert "room_to_resistance" not in check_names(r)
    assert r.warnings == ()
    assert r.quality_total == 2
    assert r.snapshot is s


def test_off_room_still_records_metric():
    r = evaluate_in_play(snap(daily_resistance=7.00), InPlayConfig(room_level=Level.OFF))
    assert r.metrics.room_to_resistance_pct == pytest.approx(0.5 / 6.5)


# --- Raw data preservation ---------------------------------------------------


def test_failing_candidate_preserves_raw_snapshot_metrics_and_config():
    s = snap(float_shares=50_000_000, price=1.50, previous_close=1.40, daily_resistance=3.0)
    config = InPlayConfig()
    r = evaluate_in_play(s, config)
    assert not r.qualified
    assert r.snapshot is s
    assert r.config is config
    assert r.metrics.pct_change == pytest.approx(0.10 / 1.40)
    assert r.metrics.volume_vs_avg_daily == pytest.approx(8.0)
    assert r.snapshot.float_shares == 50_000_000
    assert r.snapshot.premarket_volume == 1_200_000


# --- Principles --------------------------------------------------------------


def test_evaluation_is_deterministic():
    s = snap(catalyst=None, float_shares=15_000_000)
    assert evaluate_in_play(s, CONFIG) == evaluate_in_play(s, CONFIG)


def test_evaluation_does_not_mutate_inputs():
    s, config = snap(), InPlayConfig()
    before = (replace(s), replace(config))
    evaluate_in_play(s, config)
    assert (s, config) == before


def test_result_is_immutable():
    r = evaluate_in_play(snap(), CONFIG)
    with pytest.raises(FrozenInstanceError):
        r.qualified = False


# --- Universe ----------------------------------------------------------------


def test_universe_returns_every_result_in_input_order():
    snaps = [snap(ticker="AAAA"), snap(ticker="BBBB", float_shares=90_000_000), "garbage", snap(ticker="CCCC")]
    results = evaluate_universe(snaps, CONFIG)
    assert isinstance(results, tuple)
    assert [r.ticker for r in results] == ["AAAA", "BBBB", None, "CCCC"]
    assert [r.qualified for r in results] == [True, False, False, True]


def test_universe_empty():
    assert evaluate_universe([], CONFIG) == ()


def test_universe_requires_config():
    with pytest.raises(TypeError):
        evaluate_universe([snap()], None)
