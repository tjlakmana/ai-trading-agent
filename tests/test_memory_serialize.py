"""Tests for memory/serialize.py and memory/classification.py."""

import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from core.market import Catalyst, CatalystType
from data.finviz import schema as col
from data.finviz.config import FinvizScreenConfig
from data.finviz.scan import run_in_play_scan
from memory import serialize as ser
from memory.classification import ScanClass, classify
from strategy.in_play import evaluate_in_play
from strategy.in_play_config import InPlayConfig, Level
from tests.finviz_fixtures import T_REGULAR, FakeClient, csv_text, row
from tests.test_in_play import snap

# --- Snapshot / catalyst round trip ------------------------------------------


@pytest.mark.parametrize("s", [
    snap(),
    snap(open_price=None, average_daily_volume=None, premarket_volume=None, float_shares=None,
         catalyst=None, daily_resistance=None, resistance_checked=False),
    snap(catalyst=Catalyst(present=False, type=None, headline=None, source="manual")),
    snap(catalyst=Catalyst(present=True, type=CatalystType.OFFERING, headline="Offering", source="news_feed")),
])
def test_snapshot_round_trip(s):
    d = ser.snapshot_to_dict(s)
    assert ser.snapshot_from_dict(json.loads(json.dumps(d))) == s


def test_snapshot_none_round_trip():
    assert ser.snapshot_to_dict(None) is None and ser.snapshot_from_dict(None) is None


def test_snapshot_with_unexpected_fields_rejected():
    d = ser.snapshot_to_dict(snap())
    d["relative_volume"] = 9.5
    with pytest.raises(ValueError, match="do not match"):
        ser.snapshot_from_dict(d)


def test_naive_stored_datetime_rejected():
    with pytest.raises(ValueError, match="UTC offset"):
        ser.datetime_from_str("2026-10-28T14:00:00")


def test_datetimes_keep_offset():
    assert ser.datetime_from_str(ser.datetime_to_str(T_REGULAR)) == T_REGULAR


# --- Config round trip -------------------------------------------------------


@pytest.mark.parametrize("config", [
    InPlayConfig(),
    InPlayConfig(min_cumulative_volume=500_000, min_premarket_cumulative_volume=100_000,
                 catalyst_level=Level.HARD, room_level=Level.OFF, max_float_shares=None,
                 negative_catalyst_types=frozenset({CatalystType.OFFERING, CatalystType.MERGER_ACQUISITION})),
])
def test_in_play_config_round_trip(config):
    d = json.loads(json.dumps(ser.in_play_config_to_dict(config)))
    assert ser.in_play_config_from_dict(d) == config


def test_fields_added_later_take_defaults():
    d = ser.in_play_config_to_dict(InPlayConfig())
    del d["min_cumulative_volume"]  # as if recorded before the field existed
    assert ser.in_play_config_from_dict(d) == InPlayConfig()


def test_unknown_config_field_rejected():
    d = {**ser.in_play_config_to_dict(InPlayConfig()), "secret_override": 1}
    with pytest.raises(ValueError, match="unknown fields"):
        ser.in_play_config_from_dict(d)


def test_invalid_stored_config_value_rejected_by_config_validation():
    d = {**ser.in_play_config_to_dict(InPlayConfig()), "min_price": -1}
    with pytest.raises(ValueError, match="min_price"):
        ser.in_play_config_from_dict(d)


def test_screen_config_round_trip():
    c = FinvizScreenConfig(filters=("sh_price_2to20", "ta_change_u"), tickers=("AAPL",))
    assert ser.screen_config_from_dict(ser.screen_config_to_dict(c)) == c


# --- Audit records -----------------------------------------------------------


def test_result_and_record_dicts_are_strict_json():
    scan = run_in_play_scan(FakeClient(csv_text(row(), row({col.TICKER: "EFGH", col.PRICE: "-"}))),
                            clock=lambda: T_REGULAR)
    for c in scan.candidates:
        json.dumps(ser.result_to_dict(c.result), allow_nan=False)
        json.dumps(ser.record_to_dict(c.record), allow_nan=False)
    rejected = ser.record_to_dict(scan.rejected[0])
    assert rejected["snapshot"] is None and rejected["errors"] == ["Price is missing"]


def test_record_dict_keeps_raw_cells_and_freshness():
    scan = run_in_play_scan(FakeClient(csv_text(row())), clock=lambda: T_REGULAR)
    d = ser.record_to_dict(scan.candidates[0].record)
    assert d["raw"][col.PRICE] == "6.50"
    assert d["fetched_at"] == T_REGULAR.isoformat()
    assert d["quote_time"] is None
    assert d["quote_freshness"] == "UNKNOWN"
    assert d["vendor"]["relative_volume"] == 9.5


def test_result_dict_keeps_every_check():
    r = evaluate_in_play(snap(), InPlayConfig(min_cumulative_volume=500_000))
    d = ser.result_to_dict(r)
    assert len(d["hard_checks"]) == len(r.hard_checks) and len(d["quality_checks"]) == len(r.quality_checks)
    first = d["hard_checks"][0]
    assert set(first) == {"name", "level", "status", "actual", "threshold", "message"}


# --- Classification ----------------------------------------------------------


def test_qualified():
    k = classify(evaluate_in_play(snap(), InPlayConfig()))
    assert (k.scan_class, k.failed_hard_checks, k.hard_failures) == (ScanClass.QUALIFIED, (), 0)


def test_one_failed_hard_check_is_near_miss():
    k = classify(evaluate_in_play(snap(price=5.20), InPlayConfig()))  # +4% only
    assert k.scan_class is ScanClass.NEAR_MISS
    assert k.failed_hard_checks == ("min_pct_change",)


def test_one_unknown_hard_check_is_near_miss():
    k = classify(evaluate_in_play(snap(float_shares=None), InPlayConfig()))
    assert k.scan_class is ScanClass.NEAR_MISS
    assert k.failed_hard_checks == ("max_float_shares",)


def test_two_failed_hard_checks_are_filtered_out():
    k = classify(evaluate_in_play(snap(price=5.20, float_shares=50_000_000), InPlayConfig()))
    assert k.scan_class is ScanClass.FILTERED_OUT and k.hard_failures == 2


def test_invalid_data_is_filtered_out():
    k = classify(evaluate_in_play(snap(price=-1.0), InPlayConfig()))
    assert (k.scan_class, k.failed_hard_checks, k.hard_failures) == (ScanClass.FILTERED_OUT, ("invalid_data",), None)


def test_preferred_failures_do_not_affect_class():
    k = classify(evaluate_in_play(snap(catalyst=None, resistance_checked=False, daily_resistance=None),
                                  InPlayConfig()))
    assert k.scan_class is ScanClass.QUALIFIED


def test_classification_never_changes_qualification():
    for s in (snap(), snap(price=5.20), snap(price=25.0, previous_close=24.0), snap(float_shares=None)):
        r = evaluate_in_play(s, InPlayConfig())
        assert (classify(r).scan_class is ScanClass.QUALIFIED) is r.qualified


def test_classify_requires_result():
    with pytest.raises(TypeError):
        classify({"qualified": True})
