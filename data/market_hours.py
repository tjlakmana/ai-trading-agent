"""US equity market session classification (deterministic, standard library only).

Converts a timezone-aware datetime to US Eastern time with the US daylight
saving rule in force since 2007 (second Sunday of March to first Sunday of
November, switching at 2:00 local time). No IANA time zone database is needed;
Python on Windows ships without one.

Sessions, Eastern time, Monday to Friday:
    PREMARKET    04:00 - 09:30
    REGULAR      09:30 - 16:00
    AFTER_HOURS  16:00 - 20:00
    CLOSED       otherwise, and all weekend

Exchange holidays and early closes are NOT modelled: a holiday is classified
as an ordinary weekday.
"""

from datetime import date, datetime, time, timedelta, timezone
from enum import Enum

EST = timezone(timedelta(hours=-5), "EST")
EDT = timezone(timedelta(hours=-4), "EDT")

PREMARKET_OPEN = time(4, 0)
REGULAR_OPEN = time(9, 30)
REGULAR_CLOSE = time(16, 0)
AFTER_HOURS_CLOSE = time(20, 0)


class Session(str, Enum):
    PREMARKET = "PREMARKET"
    REGULAR = "REGULAR"
    AFTER_HOURS = "AFTER_HOURS"
    CLOSED = "CLOSED"


def _nth_sunday(year: int, month: int, n: int) -> date:
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def to_us_eastern(dt: datetime) -> datetime:
    """Return dt in US Eastern time (EST or EDT). Raises ValueError if dt is naive."""
    if not isinstance(dt, datetime) or dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("dt must be a timezone-aware datetime")
    utc = dt.astimezone(timezone.utc)
    dst_start = datetime.combine(_nth_sunday(utc.year, 3, 2), time(7), timezone.utc)  # 2:00 EST
    dst_end = datetime.combine(_nth_sunday(utc.year, 11, 1), time(6), timezone.utc)  # 2:00 EDT
    return utc.astimezone(EDT if dst_start <= utc < dst_end else EST)


def session_at(dt: datetime) -> Session:
    """Classify a timezone-aware moment into a US equity trading session."""
    et = to_us_eastern(dt)
    if et.weekday() >= 5:
        return Session.CLOSED
    t = et.time()
    if PREMARKET_OPEN <= t < REGULAR_OPEN:
        return Session.PREMARKET
    if REGULAR_OPEN <= t < REGULAR_CLOSE:
        return Session.REGULAR
    if REGULAR_CLOSE <= t < AFTER_HOURS_CLOSE:
        return Session.AFTER_HOURS
    return Session.CLOSED
