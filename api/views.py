"""Turn stored scanner history into API views (pure functions, no I/O).

Values are grouped by origin (market / calculated / vendor). The only metric
computed here is pct_below_day_high, a snapshot at fetch time, from raw
Finviz day high and price. Every other calculated value comes from the
stored deterministic in-play result.
"""

from datetime import datetime

from data.finviz import schema as col
from data.market_hours import to_us_eastern
from memory import serialize as ser
from memory.scan_store import REJECTED, RowSummary, RunSummary

FINVIZ_FRESHNESS_NOTE = ("fetched_at is when we received the data. Finviz provides no quote timestamp, "
                         "so quote freshness is UNKNOWN.")
SORT_KEYS = ("row_number", "ticker", "price", "pct_change", "gap_pct", "volume_vs_avg_daily",
             "cumulative_volume", "float_shares", "pct_below_day_high", "vendor_relative_volume")
STATUS_ORDER = ("QUALIFIED", "NEAR_MISS", "FILTERED_OUT", REJECTED)


def freshness(fetched_at: datetime | None, now: datetime, quote_freshness: str = "UNKNOWN") -> dict:
    return {
        "fetched_at": fetched_at,
        "fetched_at_et": f"{to_us_eastern(fetched_at):%Y-%m-%d %H:%M:%S %Z}" if fetched_at else None,
        "quote_time": None,
        "quote_freshness": quote_freshness,
        "seconds_since_fetch": round((now - fetched_at).total_seconds(), 1) if fetched_at else None,
        "note": FINVIZ_FRESHNESS_NOTE,
    }


def counts(run: RunSummary) -> dict:
    return {"rows": run.row_count, "qualified": run.qualified_count, "near_miss": run.near_miss_count,
            "filtered_out": run.filtered_out_count, "rejected": run.rejected_count}


def run_view(run: RunSummary, now: datetime) -> dict:
    return {
        "run_id": run.run_id, "short_id": run.run_id[:8], "profile": run.profile_name, "status": run.status,
        "provider": run.provider, "started_at": run.started_at, "recorded_at": run.recorded_at,
        "session": run.session, "counts": counts(run),
        "error": {"type": run.error_type, "message": run.error_message} if run.status == "ERROR" else None,
        "screen_config": run.screen_config, "in_play_config": run.in_play_config,
        "payload_sha256": run.payload_sha256,
        "freshness": freshness(run.fetched_at, now, run.quote_freshness.value),
    }


def _pct_below_high(price, high) -> float | None:
    if price is None or high is None or high <= 0:
        return None
    return (high - price) / high


def _cell(raw: dict, name: str) -> str | None:
    value = (raw.get(name) or "").strip()
    return None if value in ("", "-") else value


def row_view(entry: dict) -> dict:
    """An index-level view of one payload entry (candidate or rejected)."""
    record = entry["record"]
    raw, snap = record["raw"], record["snapshot"] or {}
    result = entry.get("result") or {}
    metrics = result.get("metrics") or {}
    hard = result.get("hard_checks") or []
    failed = [c["name"] for c in hard if c["status"] != "PASS"]
    if entry["kind"] == "candidate" and not result.get("valid_data"):
        failed = ["invalid_data"]
    price = snap.get("price")
    return {
        "row_number": record["row_number"],
        "ticker": record["ticker"],
        "company": _cell(raw, col.COMPANY),
        "exchange": _cell(raw, col.EXCHANGE),
        "status": entry.get("classification", REJECTED),
        "hard_failures": None if entry["kind"] == "rejected" or not result.get("valid_data") else len(failed),
        "failed_hard_checks": failed if entry["kind"] == "candidate" else [],
        "reasons": list(result.get("reasons") or record["errors"]),
        "warnings_count": len(result.get("warnings") or []) + len(record["warnings"]),
        "market": {
            "price": price, "previous_close": snap.get("previous_close"), "open_price": snap.get("open_price"),
            "day_high": record["day_high"], "day_low": record["day_low"],
            "cumulative_volume": snap.get("cumulative_volume"),
            "average_daily_volume": snap.get("average_daily_volume"),
            "float_shares": snap.get("float_shares"), "trades": record["trades"],
        },
        "calculated": {
            "pct_change": metrics.get("pct_change"), "gap_pct": metrics.get("gap_pct"),
            "volume_vs_avg_daily": metrics.get("volume_vs_avg_daily"),
            "room_to_resistance_pct": metrics.get("room_to_resistance_pct"),
            "pct_below_day_high": _pct_below_high(price, record["day_high"]),
        },
        "vendor": dict(record["vendor"]),
        "news": {"time": _cell(raw, col.NEWS_TIME), "title": _cell(raw, col.NEWS_TITLE),
                 "classification": "UNCLASSIFIED"},
    }


def row_detail(entry: dict, now: datetime) -> dict:
    record, result = entry["record"], entry.get("result") or {}
    fetched_at = ser.datetime_from_str(record["fetched_at"])
    return {
        **row_view(entry),
        "qualified": result.get("qualified"),
        "valid_data": result.get("valid_data"),
        "hard_checks": result.get("hard_checks") or [],
        "quality_checks": result.get("quality_checks") or [],
        "quality_passed": result.get("quality_passed"),
        "quality_total": result.get("quality_total"),
        "warnings": list(result.get("warnings") or []) + list(record["warnings"]),
        "normalization_errors": list(record["errors"]),
        "raw": dict(record["raw"]),
        "session": record["session"],
        "freshness": freshness(fetched_at, now, record["quote_freshness"]),
    }


def all_entries(payload: dict) -> list[dict]:
    return ([{"kind": "candidate", **c} for c in payload["candidates"]]
            + [{"kind": "rejected", "record": r} for r in payload["rejected"]])


def _sort_value(view: dict, key: str):
    if key in ("row_number", "ticker"):
        return view[key]
    if key == "vendor_relative_volume":
        return view["vendor"]["relative_volume"]
    if key in view["calculated"]:
        return view["calculated"][key]
    return view["market"][key]


def select_rows(views: list[dict], *, statuses: set[str] | None, ticker: str | None,
                sort: str, descending: bool) -> list[dict]:
    """Filter and sort row views. Missing values always sort last."""
    if sort not in SORT_KEYS:
        raise ValueError(f"sort must be one of {list(SORT_KEYS)}")
    out = [v for v in views
           if (statuses is None or v["status"] in statuses)
           and (ticker is None or (v["ticker"] or "").startswith(ticker))]
    present = [v for v in out if _sort_value(v, sort) is not None]
    missing = [v for v in out if _sort_value(v, sort) is None]
    present.sort(key=lambda v: _sort_value(v, sort), reverse=descending)
    return present + sorted(missing, key=lambda v: v["row_number"])


def ticker_observation(started_at: datetime, profile: str, row: RowSummary) -> dict:
    return {
        "run_id": row.run_id, "short_id": row.run_id[:8], "started_at": started_at, "profile": profile,
        "row_number": row.row_number, "status": row.status, "failed_hard_checks": list(row.failed_checks),
        "price": row.price, "pct_change": row.pct_change, "cumulative_volume": row.cumulative_volume,
        "volume_vs_avg_daily": row.volume_vs_avg_daily, "float_shares": row.float_shares,
    }
