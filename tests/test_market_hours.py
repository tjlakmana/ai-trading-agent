"""Tests for data/market_hours.py."""

from datetime import datetime, timedelta, timezone

import pytest

from data.market_hours import EDT, EST, Session, session_at, to_us_eastern

UTC = timezone.utc


@pytest.mark.parametrize("utc, tz", [
    # 2026 DST starts Sun Mar 8 at 2:00 EST (07:00 UTC) and ends Sun Nov 1 at 2:00 EDT (06:00 UTC).
    (datetime(2026, 3, 8, 6, 59, tzinfo=UTC), EST),
    (datetime(2026, 3, 8, 7, 0, tzinfo=UTC), EDT),
    (datetime(2026, 11, 1, 5, 59, tzinfo=UTC), EDT),
    (datetime(2026, 11, 1, 6, 0, tzinfo=UTC), EST),
    (datetime(2026, 1, 15, 12, 0, tzinfo=UTC), EST),
    (datetime(2026, 7, 15, 12, 0, tzinfo=UTC), EDT),
    (datetime(2027, 3, 14, 7, 0, tzinfo=UTC), EDT),  # 2027: second Sunday is Mar 14
])
def test_dst_transitions(utc, tz):
    assert to_us_eastern(utc).tzinfo is tz


def test_conversion_keeps_the_instant():
    utc = datetime(2026, 10, 28, 18, 21, tzinfo=UTC)
    et = to_us_eastern(utc)
    assert et == utc
    assert (et.hour, et.minute) == (14, 21)


def test_non_utc_input_is_accepted():
    tokyo = timezone(timedelta(hours=9))
    assert to_us_eastern(datetime(2026, 10, 29, 3, 30, tzinfo=tokyo)).hour == 14


@pytest.mark.parametrize("bad", [datetime(2026, 10, 28, 14, 0), "2026-10-28", None])
def test_naive_or_non_datetime_rejected(bad):
    with pytest.raises(ValueError):
        to_us_eastern(bad)


@pytest.mark.parametrize("utc_hour, utc_minute, session", [
    # Wednesday 2026-10-28 is EDT (UTC-4).
    (7, 59, Session.CLOSED),         # 03:59
    (8, 0, Session.PREMARKET),       # 04:00
    (13, 29, Session.PREMARKET),     # 09:29
    (13, 30, Session.REGULAR),       # 09:30
    (19, 59, Session.REGULAR),       # 15:59
    (20, 0, Session.AFTER_HOURS),    # 16:00
    (23, 59, Session.AFTER_HOURS),   # 19:59
])
def test_weekday_sessions_edt(utc_hour, utc_minute, session):
    assert session_at(datetime(2026, 10, 28, utc_hour, utc_minute, tzinfo=UTC)) is session


def test_after_hours_end_rolls_into_next_utc_day():
    assert session_at(datetime(2026, 10, 29, 0, 0, tzinfo=UTC)) is Session.CLOSED  # 20:00 EDT


def test_regular_open_in_winter_uses_est():
    assert session_at(datetime(2026, 12, 2, 14, 29, tzinfo=UTC)) is Session.PREMARKET  # 09:29 EST
    assert session_at(datetime(2026, 12, 2, 14, 30, tzinfo=UTC)) is Session.REGULAR  # 09:30 EST


@pytest.mark.parametrize("day", [31, 1])  # Sat Oct 31, Sun Nov 1 2026
def test_weekend_is_closed(day):
    month = 10 if day == 31 else 11
    assert session_at(datetime(2026, month, day, 15, 0, tzinfo=UTC)) is Session.CLOSED
