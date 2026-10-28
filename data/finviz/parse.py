"""Parse Finviz screener CSV into FinvizRecords and ScannerSnapshots.

Per row:
    raw CSV cells (kept unchanged) -> unit conversion -> ScannerSnapshot
                                   -> VendorMetrics (Finviz-calculated, recorded only)

Rules:
- The header must contain exactly the verified columns; anything else rejects
  the whole response (FinvizResponseError), so a Finviz format change fails
  loudly instead of shifting data.
- A row missing or garbling a required field (Ticker, Price, Prev Close,
  Volume) gets no snapshot. It is kept with its errors for debugging.
- Optional fields that are missing ('' or '-') become None, and the in-play
  filter fails them closed where they are HARD. Range checks (positive price
  and so on) stay in strategy.in_play.validate_snapshot.
- Units: Average Volume x 1,000; Shares Float x 1,000,000; Volume is whole
  shares; prices are dollars.
- Finviz has no quote timestamp. as_of is set to fetched_at (when we
  observed the data), quote_time is None, and quote_freshness is UNKNOWN.
- Premarket (by fetched_at): open_price is None, matching ScannerSnapshot's
  "None before the regular-session open". Finviz column behaviour outside
  the regular session is unverified, so every such row gets a warning.
- Vendor metrics never feed the snapshot or any in-play check.
"""

import csv
import io
import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from types import MappingProxyType

from core.market import ScannerSnapshot
from data.finviz import schema as col
from data.finviz.errors import FinvizResponseError
from data.market_hours import Session, session_at

SOURCE = "finviz_elite"
_MISSING = frozenset({"", "-"})


class QuoteFreshness(str, Enum):
    VERIFIED = "VERIFIED"  # never set for Finviz: there is no quote timestamp
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class VendorMetrics:
    """Finviz-calculated values. Discovery and research data only.

    Percentages are fractions (+12.5% -> 0.125). Relative volume uses Finviz's
    own undocumented formula; it is not our volume_vs_avg_daily.
    """
    relative_volume: float | None
    change_pct: float | None
    change_from_open_pct: float | None
    gap_pct: float | None
    perf_1m_pct: float | None
    perf_5m_pct: float | None
    perf_10m_pct: float | None
    perf_15m_pct: float | None
    perf_30m_pct: float | None
    perf_1h_pct: float | None


@dataclass(frozen=True)
class FinvizRecord:
    row_number: int  # 1-based data row in the CSV
    ticker: str | None
    raw: Mapping[str, str]  # unchanged CSV cells
    fetched_at: datetime  # when we received the response (timezone-aware)
    quote_time: datetime | None  # always None: Finviz provides no quote timestamp
    quote_freshness: QuoteFreshness
    session: Session  # derived from fetched_at
    day_high: float | None  # raw dollars; not part of ScannerSnapshot
    day_low: float | None
    trades: int | None
    vendor: VendorMetrics
    snapshot: ScannerSnapshot | None  # None when required data is missing or malformed
    errors: tuple[str, ...]  # why there is no snapshot
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return self.snapshot is not None


# --- Cell parsing ------------------------------------------------------------


def _cell(row: Mapping[str, str], name: str) -> str | None:
    """Stripped cell text, or None when the cell is missing ('' or '-')."""
    text = row[name].strip()
    return None if text in _MISSING else text


def _number(row, name, problems: list[str], required: bool = False) -> float | None:
    text = _cell(row, name)
    if text is None:
        if required:
            problems.append(f"{name} is missing")
        return None
    try:
        value = float(text)
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        problems.append(f"{name} is not a finite number: {text!r}")
        return None
    return value


def _whole(row, name, problems: list[str], required: bool = False) -> int | None:
    text = _cell(row, name)
    if text is None:
        if required:
            problems.append(f"{name} is missing")
        return None
    if not (text.isascii() and text.isdigit()):
        problems.append(f"{name} is not a whole number: {text!r}")
        return None
    return int(text)


def _percent(row, name, problems: list[str]) -> float | None:
    text = _cell(row, name)
    if text is None:
        return None
    if not text.endswith("%"):
        problems.append(f"{name} is not a percentage: {text!r}")
        return None
    try:
        value = float(text[:-1])
    except ValueError:
        value = math.nan
    if not math.isfinite(value):
        problems.append(f"{name} is not a finite percentage: {text!r}")
        return None
    return value / 100


def _scaled(row, name, multiplier: int, problems: list[str]) -> float | None:
    value = _number(row, name, problems)
    return None if value is None else value * multiplier


# --- Row normalization -------------------------------------------------------


def _vendor_metrics(row, warnings: list[str]) -> VendorMetrics:
    return VendorMetrics(
        relative_volume=_number(row, col.RELATIVE_VOLUME, warnings),
        change_pct=_percent(row, col.CHANGE, warnings),
        change_from_open_pct=_percent(row, col.CHANGE_FROM_OPEN, warnings),
        gap_pct=_percent(row, col.GAP, warnings),
        perf_1m_pct=_percent(row, col.PERF_1M, warnings),
        perf_5m_pct=_percent(row, col.PERF_5M, warnings),
        perf_10m_pct=_percent(row, col.PERF_10M, warnings),
        perf_15m_pct=_percent(row, col.PERF_15M, warnings),
        perf_30m_pct=_percent(row, col.PERF_30M, warnings),
        perf_1h_pct=_percent(row, col.PERF_1H, warnings),
    )


def _record(row_number: int, row: dict[str, str], fetched_at: datetime, session: Session) -> FinvizRecord:
    errors: list[str] = []
    warnings: list[str] = []

    ticker = _cell(row, col.TICKER)
    if ticker is None:
        errors.append(f"{col.TICKER} is missing")
    price = _number(row, col.PRICE, errors, required=True)
    previous_close = _number(row, col.PREV_CLOSE, errors, required=True)
    volume = _whole(row, col.VOLUME, errors, required=True)

    # Optional raw fields: a bad value becomes None (the filter fails it closed) plus a warning.
    open_price = _number(row, col.OPEN, warnings)
    average_volume = _scaled(row, col.AVERAGE_VOLUME, col.AVERAGE_VOLUME_MULTIPLIER, warnings)
    float_millions = _number(row, col.SHARES_FLOAT, warnings)
    float_shares = round(float_millions * col.SHARES_FLOAT_MULTIPLIER) if float_millions is not None else None
    day_high = _number(row, col.HIGH, warnings)
    day_low = _number(row, col.LOW, warnings)
    trades = _whole(row, col.TRADES, warnings)
    vendor = _vendor_metrics(row, warnings)

    if session is Session.PREMARKET:
        open_price = None  # no regular-session open yet
    if session is not Session.REGULAR:
        warnings.append(f"fetched during {session.value}: Finviz column behaviour outside "
                        "the regular session is unverified")

    snapshot = None
    if not errors:
        snapshot = ScannerSnapshot(
            ticker=ticker, as_of=fetched_at, source=SOURCE,
            price=price, previous_close=previous_close, open_price=open_price,
            cumulative_volume=volume, average_daily_volume=average_volume,
            premarket_volume=None,  # not provided by Finviz
            float_shares=float_shares,
            catalyst=None,  # news is recorded raw; no catalyst classification in V1
            daily_resistance=None, resistance_checked=False,  # Finviz gives no resistance level
        )
    return FinvizRecord(
        row_number=row_number, ticker=ticker, raw=MappingProxyType(dict(row)),
        fetched_at=fetched_at, quote_time=None, quote_freshness=QuoteFreshness.UNKNOWN,
        session=session, day_high=day_high, day_low=day_low, trades=trades, vendor=vendor,
        snapshot=snapshot, errors=tuple(errors), warnings=tuple(warnings),
    )


def _malformed(row_number: int, cells: list[str], header: list[str], fetched_at, session) -> FinvizRecord:
    raw = MappingProxyType({f"cell_{i}": v for i, v in enumerate(cells)})
    ticker_index = header.index(col.TICKER)
    ticker = cells[ticker_index].strip() or None if ticker_index < len(cells) else None
    vendor = VendorMetrics(*([None] * len(VendorMetrics.__dataclass_fields__)))
    return FinvizRecord(
        row_number=row_number, ticker=ticker, raw=raw, fetched_at=fetched_at,
        quote_time=None, quote_freshness=QuoteFreshness.UNKNOWN, session=session,
        day_high=None, day_low=None, trades=None, vendor=vendor, snapshot=None,
        errors=(f"row has {len(cells)} cells, expected {len(header)}",), warnings=(),
    )


# --- Public API --------------------------------------------------------------


def parse_screener_csv(text: str, fetched_at: datetime) -> tuple[FinvizRecord, ...]:
    """Parse a whole response. Raises FinvizResponseError if the response itself is unusable."""
    if not isinstance(fetched_at, datetime) or fetched_at.tzinfo is None:
        raise ValueError("fetched_at must be a timezone-aware datetime")
    if not isinstance(text, str) or not text.strip():
        raise FinvizResponseError("empty response")
    session = session_at(fetched_at)
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip("﻿"), newline="")))
    except csv.Error as exc:
        raise FinvizResponseError(f"malformed CSV: {exc}") from None

    header = [h.strip() for h in rows[0]]
    missing = sorted(col.EXPECTED_HEADERS - set(header))
    unexpected = sorted(set(header) - col.EXPECTED_HEADERS)
    if missing or unexpected or len(header) != len(set(header)):
        raise FinvizResponseError(
            f"unexpected CSV header: missing {missing}, unexpected {unexpected}"
            + (", duplicate columns" if len(header) != len(set(header)) else "")
        )

    records: list[FinvizRecord] = []
    seen: set[str] = set()
    for number, cells in enumerate(rows[1:], start=1):
        if not cells or all(not c.strip() for c in cells):
            continue  # blank line
        if len(cells) != len(header):
            records.append(_malformed(number, cells, header, fetched_at, session))
            continue
        record = _record(number, dict(zip(header, cells)), fetched_at, session)
        if record.ticker is not None and record.ticker in seen:
            record = _with_error(record, f"duplicate ticker {record.ticker!r} in response")
        if record.ticker is not None:
            seen.add(record.ticker)
        records.append(record)
    return tuple(records)


def _with_error(record: FinvizRecord, error: str) -> FinvizRecord:
    return replace(record, snapshot=None, errors=record.errors + (error,))
