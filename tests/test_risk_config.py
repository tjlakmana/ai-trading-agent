"""Tests for bot/risk_config.py."""

from dataclasses import FrozenInstanceError

import pytest

from bot.risk_config import RiskConfig

FIELDS = ("max_risk_per_trade_pct", "max_position_pct", "max_daily_loss_pct")


def test_development_defaults():
    config = RiskConfig()
    assert config.max_risk_per_trade_pct == 0.01
    assert config.max_position_pct == 0.20
    assert config.max_daily_loss_pct == 0.03


def test_config_is_immutable():
    config = RiskConfig()
    with pytest.raises(FrozenInstanceError):
        config.max_position_pct = 1.0


def test_custom_values_accepted():
    config = RiskConfig(max_risk_per_trade_pct=0.005, max_position_pct=1.0, max_daily_loss_pct=0.1)
    assert config.max_position_pct == 1.0


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [0, 0.0, -0.01, 1.01, 5, float("nan"), float("inf")])
def test_out_of_range_values_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        RiskConfig(**{field: value})


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("value", [True, False, "0.01", None])
def test_non_number_values_rejected(field, value):
    with pytest.raises(ValueError, match=field):
        RiskConfig(**{field: value})
