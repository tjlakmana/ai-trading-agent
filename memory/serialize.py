"""Explicit JSON serialization for scanner history (no pickle).

Every stored value is plain JSON: str, int, float, bool, None, list, dict.
Enums are stored by value, datetimes as ISO 8601 with their UTC offset, and
frozensets as sorted lists. Loaders exist only for the inputs needed to
replay a scan (ScannerSnapshot, Catalyst, InPlayConfig, FinvizScreenConfig).
Results are stored for audit and recomputed on replay, never loaded back as
decisions.
"""

from dataclasses import asdict, fields
from datetime import datetime

from core.market import Catalyst, CatalystType, ScannerSnapshot
from data.finviz.config import FinvizScreenConfig
from data.finviz.parse import FinvizRecord
from strategy.in_play import CheckResult, InPlayMetrics, InPlayResult
from strategy.in_play_config import InPlayConfig, Level


def datetime_to_str(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def datetime_from_str(text: str | None) -> datetime | None:
    if text is None:
        return None
    value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        raise ValueError(f"stored datetime {text!r} has no UTC offset")
    return value


# --- Catalyst / ScannerSnapshot (round-trip) ---------------------------------


def catalyst_to_dict(c: Catalyst | None) -> dict | None:
    if c is None:
        return None
    return {"present": c.present, "type": c.type.value if c.type is not None else None,
            "headline": c.headline, "source": c.source}


def catalyst_from_dict(d: dict | None) -> Catalyst | None:
    if d is None:
        return None
    return Catalyst(present=d["present"], type=CatalystType(d["type"]) if d["type"] is not None else None,
                    headline=d["headline"], source=d["source"])


_SNAPSHOT_FIELDS = tuple(f.name for f in fields(ScannerSnapshot))


def snapshot_to_dict(s: ScannerSnapshot | None) -> dict | None:
    if s is None:
        return None
    d = {name: getattr(s, name) for name in _SNAPSHOT_FIELDS}
    d["as_of"] = datetime_to_str(s.as_of)
    d["catalyst"] = catalyst_to_dict(s.catalyst)
    return d


def snapshot_from_dict(d: dict | None) -> ScannerSnapshot | None:
    if d is None:
        return None
    if set(d) != set(_SNAPSHOT_FIELDS):
        raise ValueError(f"stored snapshot fields {sorted(d)} do not match ScannerSnapshot")
    return ScannerSnapshot(**{**d, "as_of": datetime_from_str(d["as_of"]),
                              "catalyst": catalyst_from_dict(d["catalyst"])})


# --- Configs (round-trip) ----------------------------------------------------


def in_play_config_to_dict(c: InPlayConfig) -> dict:
    d = {}
    for f in fields(InPlayConfig):
        value = getattr(c, f.name)
        if isinstance(value, Level):
            value = value.value
        elif isinstance(value, frozenset):
            value = sorted(t.value for t in value)
        d[f.name] = value
    return d


def in_play_config_from_dict(d: dict) -> InPlayConfig:
    """Rebuild a config. Fields added after the record was written take their defaults."""
    known = {f.name for f in fields(InPlayConfig)}
    unknown = sorted(set(d) - known)
    if unknown:
        raise ValueError(f"stored InPlayConfig has unknown fields {unknown}")
    kwargs = dict(d)
    for name in ("catalyst_level", "room_level"):
        if name in kwargs:
            kwargs[name] = Level(kwargs[name])
    if "negative_catalyst_types" in kwargs:
        kwargs["negative_catalyst_types"] = frozenset(CatalystType(t) for t in kwargs["negative_catalyst_types"])
    return InPlayConfig(**kwargs)  # __post_init__ re-validates


def screen_config_to_dict(c: FinvizScreenConfig) -> dict:
    return {"filters": list(c.filters), "tickers": list(c.tickers)}


def screen_config_from_dict(d: dict) -> FinvizScreenConfig:
    return FinvizScreenConfig(filters=tuple(d["filters"]), tickers=tuple(d["tickers"]))


# --- Results and records (audit only) ----------------------------------------


def check_to_dict(c: CheckResult) -> dict:
    return {"name": c.name, "level": c.level.value, "status": c.status.value,
            "actual": c.actual, "threshold": c.threshold, "message": c.message}


def metrics_to_dict(m: InPlayMetrics | None) -> dict | None:
    return None if m is None else asdict(m)


def result_to_dict(r: InPlayResult) -> dict:
    """The decision record. Snapshot and config are stored once, alongside it."""
    return {
        "qualified": r.qualified,
        "valid_data": r.valid_data,
        "reasons": list(r.reasons),
        "warnings": list(r.warnings),
        "hard_checks": [check_to_dict(c) for c in r.hard_checks],
        "quality_checks": [check_to_dict(c) for c in r.quality_checks],
        "quality_passed": r.quality_passed,
        "quality_total": r.quality_total,
        "metrics": metrics_to_dict(r.metrics),
    }


def record_to_dict(r: FinvizRecord) -> dict:
    return {
        "row_number": r.row_number,
        "ticker": r.ticker,
        "raw": dict(r.raw),  # unchanged CSV cells
        "fetched_at": datetime_to_str(r.fetched_at),
        "quote_time": datetime_to_str(r.quote_time),
        "quote_freshness": r.quote_freshness.value,
        "session": r.session.value,
        "day_high": r.day_high,
        "day_low": r.day_low,
        "trades": r.trades,
        "vendor": asdict(r.vendor),
        "snapshot": snapshot_to_dict(r.snapshot),
        "errors": list(r.errors),
        "warnings": list(r.warnings),
    }
