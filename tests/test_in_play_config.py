"""Tests for strategy/in_play_config.py."""

from dataclasses import FrozenInstanceError

import pytest

from core.market import CatalystType
from strategy.in_play_config import InPlayConfig, Level

FRACTION_FIELDS = ("min_pct_change", "min_room_to_resistance_pct")
PRICE_FIELDS = ("min_price", "max_price")
RATIO_FIELDS = ("min_volume_vs_avg_daily", "preferred_volume_vs_avg_daily")
VOLUME_FIELDS = ("min_cumulative_volume", "min_premarket_cumulative_volume")
SHARE_FIELDS = ("max_float_shares", "preferred_max_float_shares") + VOLUME_FIELDS
OPTIONAL_FIELDS = PRICE_FIELDS + RATIO_FIELDS + SHARE_FIELDS + ("min_pct_change",)


def test_v1_development_defaults():
    c = InPlayConfig()
    assert (c.min_price, c.max_price) == (2.00, 20.00)
    assert c.min_pct_change == 0.10
    assert c.min_volume_vs_avg_daily == 3.0
    assert c.preferred_volume_vs_avg_daily == 5.0
    assert c.max_float_shares == 20_000_000
    assert c.preferred_max_float_shares == 10_000_000
    assert c.catalyst_level is Level.PREFERRED
    assert c.room_level is Level.PREFERRED
    assert c.min_room_to_resistance_pct == 0.20
    assert c.negative_catalyst_types == frozenset({CatalystType.OFFERING})


def test_session_volume_thresholds_disabled_by_default():
    c = InPlayConfig()
    assert c.min_cumulative_volume is None
    assert c.min_premarket_cumulative_volume is None


def test_session_volume_thresholds_are_independent():
    c = InPlayConfig(min_cumulative_volume=500_000, min_premarket_cumulative_volume=100_000)
    assert (c.min_cumulative_volume, c.min_premarket_cumulative_volume) == (500_000, 100_000)


def test_config_is_immutable():
    with pytest.raises(FrozenInstanceError):
        InPlayConfig().max_float_shares = 1


@pytest.mark.parametrize("field", OPTIONAL_FIELDS)
def test_thresholds_can_be_disabled_with_none(field):
    assert getattr(InPlayConfig(**{field: None}), field) is None


def test_all_levels_accepted():
    for level in Level:
        c = InPlayConfig(catalyst_level=level, room_level=level)
        assert c.catalyst_level is level and c.room_level is level


@pytest.mark.parametrize("field", PRICE_FIELDS + RATIO_FIELDS + FRACTION_FIELDS)
@pytest.mark.parametrize("value", [0, -1.0, float("nan"), float("inf"), True, "5"])
def test_bad_numeric_values_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        InPlayConfig(**{field: value})


@pytest.mark.parametrize("field", SHARE_FIELDS)
@pytest.mark.parametrize("value", [0, -5, 1.5, 20_000_000.0, True, "20000000"])
def test_bad_share_counts_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        InPlayConfig(**{field: value})


@pytest.mark.parametrize("lo, hi", [(20.0, 2.0), (5.0, 5.0)])
def test_price_range_must_be_ordered(lo, hi):
    with pytest.raises(ValueError, match="min_price"):
        InPlayConfig(min_price=lo, max_price=hi)


def test_preferred_float_cannot_exceed_hard_float():
    with pytest.raises(ValueError, match="preferred_max_float_shares"):
        InPlayConfig(max_float_shares=10_000_000, preferred_max_float_shares=15_000_000)


def test_preferred_volume_cannot_be_below_hard_minimum():
    with pytest.raises(ValueError, match="preferred_volume_vs_avg_daily"):
        InPlayConfig(min_volume_vs_avg_daily=5.0, preferred_volume_vs_avg_daily=3.0)


def test_preferred_values_allowed_when_hard_threshold_disabled():
    c = InPlayConfig(max_float_shares=None, preferred_max_float_shares=50_000_000,
                     min_volume_vs_avg_daily=None, preferred_volume_vs_avg_daily=1.0)
    assert c.preferred_max_float_shares == 50_000_000


@pytest.mark.parametrize("field", ["catalyst_level", "room_level"])
@pytest.mark.parametrize("value", ["HARD", None, True])
def test_levels_must_be_level_members(field, value):
    with pytest.raises(ValueError, match=field):
        InPlayConfig(**{field: value})


@pytest.mark.parametrize("value", [{CatalystType.OFFERING}, frozenset({"OFFERING"}), None])
def test_negative_catalyst_types_must_be_frozenset_of_types(value):
    with pytest.raises(ValueError, match="negative_catalyst_types"):
        InPlayConfig(negative_catalyst_types=value)


def test_empty_negative_catalyst_set_allowed():
    assert InPlayConfig(negative_catalyst_types=frozenset()).negative_catalyst_types == frozenset()
