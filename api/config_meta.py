"""InPlayConfig field metadata for the replay form, and strict override parsing.

Overrides only affect read-only replays of stored snapshots. They never
change the strategy's configuration, the scan defaults, or any risk rule.
"""

import types
import typing
from dataclasses import MISSING, fields, replace

from data.finviz.profiles import default_scan_in_play_config
from memory import serialize as ser
from strategy.in_play_config import InPlayConfig, Level

# name -> (unit, description). negative_catalyst_types is not overridable.
FIELD_INFO: dict[str, tuple[str, str]] = {
    "min_price": ("dollars", "HARD: minimum price"),
    "max_price": ("dollars", "HARD: maximum price"),
    "min_pct_change": ("fraction", "HARD: minimum % change from previous close (0.10 = +10%)"),
    "min_volume_vs_avg_daily": ("ratio", "HARD: session volume / average full-day volume (not RVOL)"),
    "max_float_shares": ("shares", "HARD: maximum float"),
    "min_cumulative_volume": ("shares", "HARD when set: regular-session minimum volume"),
    "min_premarket_cumulative_volume": ("shares", "HARD when set: premarket minimum volume"),
    "preferred_max_float_shares": ("shares", "PREFERRED: float at or below this avoids a warning"),
    "preferred_volume_vs_avg_daily": ("ratio", "PREFERRED: volume ratio at or above this avoids a warning"),
    "catalyst_level": ("level", "Category of the catalyst check (HARD / PREFERRED / OFF)"),
    "room_level": ("level", "Category of the room-to-resistance check (HARD / PREFERRED / OFF)"),
    "min_room_to_resistance_pct": ("fraction", "Minimum room to daily resistance (placeholder hypothesis)"),
}


def _kind(field) -> tuple[str, bool]:
    args = typing.get_args(field.type) if isinstance(field.type, types.UnionType) else (field.type,)
    nullable = type(None) in args
    if Level in args:
        return "level", nullable
    if int in args:
        return "int", nullable
    return "float", nullable


def _plain(value):
    return value.value if isinstance(value, Level) else value


def field_specs() -> list[dict]:
    scan_defaults = default_scan_in_play_config()
    specs = []
    for f in fields(InPlayConfig):
        if f.name not in FIELD_INFO:
            continue
        kind, nullable = _kind(f)
        unit, description = FIELD_INFO[f.name]
        default = f.default if f.default is not MISSING else None
        specs.append({"name": f.name, "kind": kind, "nullable": nullable, "unit": unit,
                      "default": _plain(default), "scan_default": _plain(getattr(scan_defaults, f.name)),
                      "description": description})
    return specs


def apply_overrides(stored_config: dict, overrides: dict) -> tuple[InPlayConfig, dict]:
    """Return (config, applied) or raise ValueError with an explanation."""
    config = ser.in_play_config_from_dict(stored_config)
    by_name = {f.name: f for f in fields(InPlayConfig) if f.name in FIELD_INFO}
    changes = {}
    for name, value in overrides.items():
        f = by_name.get(name)
        if f is None:
            raise ValueError(f"{name!r} cannot be overridden; allowed: {sorted(by_name)}")
        kind, nullable = _kind(f)
        if value is None:
            if not nullable:
                raise ValueError(f"{name} cannot be null")
            changes[name] = None
        elif kind == "level":
            if not isinstance(value, str) or value.upper() not in Level.__members__:
                raise ValueError(f"{name} must be one of {list(Level.__members__)}")
            changes[name] = Level(value.upper())
        elif kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be a whole number of shares")
            changes[name] = value
        else:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be a number")
            changes[name] = float(value)
    return replace(config, **changes), {k: _plain(v) for k, v in changes.items()}
