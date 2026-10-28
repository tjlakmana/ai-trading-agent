"""Tests for data/finviz/config.py and the verified schema constants."""

from dataclasses import FrozenInstanceError

import pytest

from data.finviz import schema
from data.finviz.config import FinvizScreenConfig, screener_params


def test_default_discovery_filters_are_the_verified_v1_screen():
    assert FinvizScreenConfig().filters == (
        "sh_price_2to20", "sh_relvol_o2", "sh_curvol_o500", "sh_float_u20", "ta_change_u",
    )
    assert FinvizScreenConfig().tickers == ()


def test_config_is_immutable():
    with pytest.raises(FrozenInstanceError):
        FinvizScreenConfig().filters = ()


@pytest.mark.parametrize("code", ["zz_bogus_code", "sh_price_1to5", "sh_relvol_o3", "SH_PRICE_2TO20", ""])
def test_unverified_filter_codes_rejected(code):
    # Finviz silently ignores unknown codes, which would widen the screen unnoticed.
    with pytest.raises(ValueError, match="unverified Finviz filter codes"):
        FinvizScreenConfig(filters=("sh_price_2to20", code))


def test_subset_of_verified_filters_allowed():
    assert FinvizScreenConfig(filters=("sh_float_u20",)).filters == ("sh_float_u20",)


@pytest.mark.parametrize("bad", [["sh_price_2to20"], "sh_price_2to20", ("sh_price_2to20", 5), None])
def test_filters_must_be_tuple_of_strings(bad):
    with pytest.raises(ValueError, match="filters"):
        FinvizScreenConfig(filters=bad)


def test_duplicate_filters_rejected():
    with pytest.raises(ValueError, match="duplicates"):
        FinvizScreenConfig(filters=("sh_float_u20", "sh_float_u20"))


@pytest.mark.parametrize("ticker", ["aapl", "AAPL&auth=x", "TOOLONGTICKER", "", "A B"])
def test_malformed_tickers_rejected(ticker):
    with pytest.raises(ValueError, match="tickers"):
        FinvizScreenConfig(filters=(), tickers=(ticker,))


def test_empty_screen_rejected():
    with pytest.raises(ValueError, match="whole market"):
        FinvizScreenConfig(filters=())


def test_ticker_only_screen_allowed():
    assert FinvizScreenConfig(filters=(), tickers=("AAPL", "BRK.B")).tickers == ("AAPL", "BRK.B")


def test_params_for_default_screen():
    params = screener_params(FinvizScreenConfig())
    assert params == {
        "type": "stocks",
        "v": "152",
        "c": ",".join(str(i) for i in sorted(schema.COLUMNS)),
        "f": "sh_price_2to20,sh_relvol_o2,sh_curvol_o500,sh_float_u20,ta_change_u",
    }


def test_params_never_contain_auth():
    params = screener_params(FinvizScreenConfig(tickers=("AAPL",)))
    assert "auth" not in params
    assert params["t"] == "AAPL"


def test_params_require_screen_config():
    with pytest.raises(TypeError):
        screener_params({"f": "zz"})


def test_column_map_is_consistent():
    assert len(schema.COLUMNS) == len(schema.EXPECTED_HEADERS)  # no duplicate header names
    # Indices verified against the live API on 2026-10-28. Above 99 they are not
    # list positions (100-124 do not exist), which is why each is pinned here.
    verified = {1: "Ticker", 25: "Shares Float", 63: "Average Volume", 64: "Relative Volume",
                65: "Price", 66: "Change", 67: "Volume", 81: "Prev Close", 86: "Open",
                87: "High", 88: "Low", 89: "Trades", 90: "Performance (1 Minute)",
                129: "Exchange", 135: "News Time", 137: "News Title"}
    assert all(schema.COLUMNS[i] == name for i, name in verified.items())
    assert not any(100 <= i <= 124 for i in schema.COLUMNS)


def test_unit_multipliers():
    assert schema.AVERAGE_VOLUME_MULTIPLIER == 1_000
    assert schema.SHARES_FLOAT_MULTIPLIER == 1_000_000
