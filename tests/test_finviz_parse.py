"""Tests for data/finviz/parse.py: CSV -> FinvizRecord / ScannerSnapshot."""

from dataclasses import FrozenInstanceError
from datetime import datetime

import pytest

from core.market import ScannerSnapshot
from data.finviz import schema as col
from data.finviz.errors import FinvizResponseError
from data.finviz.parse import SOURCE, QuoteFreshness, parse_screener_csv
from data.market_hours import Session
from strategy.in_play import validate_snapshot
from tests.finviz_fixtures import (
    BASE_ROW,
    HEADERS,
    T_AFTER_HOURS,
    T_PREMARKET,
    T_REGULAR,
    csv_text,
    row,
)


def one(changes=None, fetched_at=T_REGULAR):
    (record,) = parse_screener_csv(csv_text(row(changes)), fetched_at)
    return record


# --- Units and field mapping -------------------------------------------------


def test_units_are_converted():
    s = one().snapshot
    assert s.average_daily_volume == 500_000.0  # "500.00" thousands
    assert s.float_shares == 6_000_000  # "6.00" millions
    assert s.cumulative_volume == 4_000_000  # whole shares
    assert isinstance(s.cumulative_volume, int) and isinstance(s.float_shares, int)


def test_prices_are_raw_dollars():
    r = one()
    assert (r.snapshot.price, r.snapshot.previous_close, r.snapshot.open_price) == (6.50, 5.00, 6.00)
    assert (r.day_high, r.day_low) == (6.80, 5.90)


@pytest.mark.parametrize("raw, shares", [("17.37", 17_370_000), ("14576.70", 14_576_700_000), ("0.25", 250_000)])
def test_float_conversion_is_exact_whole_shares(raw, shares):
    # 17.37 * 1e6 is 17370000.000000004 in floating point; must round to whole shares.
    assert one({col.SHARES_FLOAT: raw}).snapshot.float_shares == shares


@pytest.mark.parametrize("raw, avg", [("43814.10", 43_814_100.0), ("71.67", 71_670.0)])
def test_average_volume_conversion(raw, avg):
    assert one({col.AVERAGE_VOLUME: raw}).snapshot.average_daily_volume == pytest.approx(avg)


def test_snapshot_contract_semantics():
    s = one().snapshot
    assert isinstance(s, ScannerSnapshot)
    assert s.ticker == "ABCD"
    assert s.source == SOURCE == "finviz_elite"
    assert s.as_of == T_REGULAR
    assert s.premarket_volume is None  # Finviz does not provide it
    assert s.catalyst is None  # not classified in V1
    assert s.daily_resistance is None and s.resistance_checked is False
    assert validate_snapshot(s) == ()


def test_record_keeps_fetch_time_separate_and_freshness_unknown():
    r = one()
    assert r.fetched_at == T_REGULAR
    assert r.quote_time is None
    assert r.quote_freshness is QuoteFreshness.UNKNOWN
    assert r.session is Session.REGULAR
    assert r.ok and r.errors == () and r.warnings == ()
    assert r.row_number == 1


def test_raw_cells_preserved_unchanged_and_read_only():
    r = one()
    assert dict(r.raw) == BASE_ROW
    with pytest.raises(TypeError):
        r.raw[col.PRICE] = "1.00"
    with pytest.raises(FrozenInstanceError):
        r.snapshot = None


def test_vendor_metrics_recorded_as_fractions():
    v = one().vendor
    assert v.relative_volume == 9.50
    assert v.change_pct == pytest.approx(0.30)
    assert v.change_from_open_pct == pytest.approx(0.0833)
    assert v.gap_pct == pytest.approx(0.20)
    assert v.perf_1m_pct == pytest.approx(0.005)
    assert v.perf_5m_pct == pytest.approx(0.012)
    assert v.perf_1h_pct == pytest.approx(0.06)


def test_vendor_metrics_never_enter_the_snapshot():
    # Wildly different vendor values give an identical snapshot.
    odd = one({col.RELATIVE_VOLUME: "0.01", col.CHANGE: "-50.00%", col.GAP: "-9.00%",
               col.PERF_5M: "-20.00%"}).snapshot
    assert odd == one().snapshot


def test_negative_percentages_parse():
    assert one({col.CHANGE: "-1.01%"}).vendor.change_pct == pytest.approx(-0.0101)


# --- Missing and malformed data ----------------------------------------------


@pytest.mark.parametrize("field", [col.TICKER, col.PRICE, col.PREV_CLOSE, col.VOLUME])
@pytest.mark.parametrize("missing", ["", "-", "  "])
def test_missing_required_field_rejects_row_with_reason(field, missing):
    r = one({field: missing})
    assert r.snapshot is None and not r.ok
    assert r.errors == (f"{field} is missing",)
    assert dict(r.raw)[field] == missing  # raw kept for debugging


@pytest.mark.parametrize("field, bad", [
    (col.PRICE, "abc"), (col.PRICE, "nan"), (col.PRICE, "inf"), (col.PREV_CLOSE, "$5.00"),
    (col.PRICE, "1,234.00"),
])
def test_malformed_required_number_rejects_row(field, bad):
    r = one({field: bad})
    assert r.snapshot is None
    assert any(field in e and repr(bad) in e for e in r.errors)


@pytest.mark.parametrize("bad", ["1.5", "-3", "1e6", "4,000,000", "abc"])
def test_volume_must_be_whole_shares(bad):
    r = one({col.VOLUME: bad})
    assert r.snapshot is None
    assert any("Volume is not a whole number" in e for e in r.errors)


def test_all_required_problems_are_reported_together():
    r = one({col.PRICE: "", col.PREV_CLOSE: "x", col.VOLUME: "-"})
    assert len(r.errors) == 3


@pytest.mark.parametrize("field, attr", [
    (col.OPEN, "open_price"), (col.AVERAGE_VOLUME, "average_daily_volume"),
    (col.SHARES_FLOAT, "float_shares"),
])
def test_missing_optional_field_becomes_none(field, attr):
    r = one({field: "-"})
    assert r.ok
    assert getattr(r.snapshot, attr) is None
    assert r.warnings == ()


def test_malformed_optional_field_becomes_none_with_warning():
    r = one({col.SHARES_FLOAT: "lots"})
    assert r.ok and r.snapshot.float_shares is None
    assert any("Shares Float" in w for w in r.warnings)


def test_missing_day_high_and_trades_are_none():
    r = one({col.HIGH: "", col.LOW: "-", col.TRADES: ""})
    assert (r.day_high, r.day_low, r.trades) == (None, None, None)
    assert r.ok


def test_malformed_vendor_metric_is_warning_not_rejection():
    r = one({col.CHANGE: "12.0", col.RELATIVE_VOLUME: "high"})
    assert r.ok
    assert r.vendor.change_pct is None and r.vendor.relative_volume is None
    assert len(r.warnings) == 2


def test_out_of_range_values_are_left_to_strategy_validation():
    # The parser converts; strategy.validate_snapshot decides ranges, explained there.
    r = one({col.PRICE: "0", col.SHARES_FLOAT: "-1.00"})
    assert r.ok
    errors = validate_snapshot(r.snapshot)
    assert any("price" in e for e in errors) and any("float_shares" in e for e in errors)


# --- Sessions ----------------------------------------------------------------


def test_premarket_has_no_open_price_and_warns():
    r = one(fetched_at=T_PREMARKET)
    assert r.session is Session.PREMARKET
    assert r.snapshot.open_price is None  # ScannerSnapshot: None before the regular open
    assert any("PREMARKET" in w and "unverified" in w for w in r.warnings)


def test_after_hours_keeps_open_and_warns():
    r = one(fetched_at=T_AFTER_HOURS)
    assert r.session is Session.AFTER_HOURS
    assert r.snapshot.open_price == 6.00
    assert any("AFTER_HOURS" in w for w in r.warnings)


# --- Whole-response structure ------------------------------------------------


def test_header_only_response_has_no_rows():
    assert parse_screener_csv(csv_text(), T_REGULAR) == ()


@pytest.mark.parametrize("text", ["", "   \n"])
def test_empty_response_rejected(text):
    with pytest.raises(FinvizResponseError, match="empty"):
        parse_screener_csv(text, T_REGULAR)


def test_missing_column_rejects_response():
    headers = [h for h in HEADERS if h != col.PREV_CLOSE]
    with pytest.raises(FinvizResponseError, match="missing \\['Prev Close'\\]"):
        parse_screener_csv(csv_text(row(), headers=headers), T_REGULAR)


def test_unexpected_column_rejects_response():
    with pytest.raises(FinvizResponseError, match="unexpected \\['P/E'\\]"):
        parse_screener_csv(csv_text(row(), headers=HEADERS + ["P/E"]), T_REGULAR)


def test_renamed_column_rejects_response():
    headers = ["Volume (shares)" if h == col.VOLUME else h for h in HEADERS]
    with pytest.raises(FinvizResponseError, match="unexpected CSV header"):
        parse_screener_csv(csv_text(row(), headers=headers), T_REGULAR)


def test_duplicate_column_rejects_response():
    with pytest.raises(FinvizResponseError, match="duplicate"):
        parse_screener_csv(csv_text(row(), headers=HEADERS + [col.PRICE]), T_REGULAR)


def test_html_body_rejected_as_unexpected_header():
    with pytest.raises(FinvizResponseError):
        parse_screener_csv("<html><body>Please log in</body></html>", T_REGULAR)


def test_column_order_does_not_matter():
    records = parse_screener_csv(csv_text(row(), headers=list(reversed(HEADERS))), T_REGULAR)
    assert records[0].snapshot == one().snapshot


def test_bom_is_tolerated():
    assert parse_screener_csv("\ufeff" + csv_text(row()), T_REGULAR)[0].ok


def test_short_row_is_kept_as_rejected():
    text = csv_text(row()) + "EFGH,Efgh Inc\r\n" + csv_text(row({col.TICKER: "IJKL"})).split("\r\n", 1)[1]
    records = parse_screener_csv(text, T_REGULAR)
    assert [r.ticker for r in records] == ["ABCD", "EFGH", "IJKL"]
    bad = records[1]
    assert bad.snapshot is None
    assert bad.errors == (f"row has 2 cells, expected {len(HEADERS)}",)
    assert bad.row_number == 2
    assert records[0].ok and records[2].ok


def test_long_row_is_kept_as_rejected():
    text = csv_text(row()).rstrip("\r\n") + ",extra\r\n"
    (r,) = parse_screener_csv(text, T_REGULAR)
    assert r.snapshot is None and "cells" in r.errors[0]


def test_duplicate_ticker_rejects_the_repeat():
    records = parse_screener_csv(csv_text(row(), row({col.PRICE: "7.00"})), T_REGULAR)
    assert records[0].ok
    assert records[1].snapshot is None
    assert "duplicate ticker 'ABCD'" in records[1].errors[0]


def test_blank_lines_are_skipped():
    text = csv_text(row()) + "\r\n\r\n"
    assert len(parse_screener_csv(text, T_REGULAR)) == 1


def test_quoted_cells_with_commas_parse():
    r = one({col.COMPANY: "Abcd, Inc.", col.NEWS_TITLE: 'Abcd "surges", hits high'})
    assert r.ok and r.raw[col.COMPANY] == "Abcd, Inc."


def test_rows_keep_response_order():
    tickers = ["ZZZZ", "AAAA", "MMMM"]
    records = parse_screener_csv(csv_text(*(row({col.TICKER: t}) for t in tickers)), T_REGULAR)
    assert [r.ticker for r in records] == tickers
    assert [r.row_number for r in records] == [1, 2, 3]


@pytest.mark.parametrize("bad", [datetime(2026, 10, 28, 14, 0), "2026-10-28", None])
def test_fetched_at_must_be_timezone_aware(bad):
    with pytest.raises(ValueError, match="fetched_at"):
        parse_screener_csv(csv_text(row()), bad)
