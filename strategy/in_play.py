"""Deterministic in-play stock filter (strategy layer 1 of 4).

    raw ScannerSnapshot -> deterministic metrics -> configurable V1 checks -> InPlayResult

"Qualified" means only that a stock may proceed to the momentum-impulse stage.
It is NOT a trade signal and NOT a TradeProposal.

Every check runs on every valid snapshot (no short-circuiting), and the raw
snapshot, derived metrics, and config are always preserved in the result, so
paper-trading outcomes can later be used to tune thresholds and categories.
No AI participates: numeric thresholds are evaluated only by this module.

Derived metrics:
    pct_change             = (price - previous_close) / previous_close
    gap_pct                = (open_price - previous_close) / previous_close   (None before open)
    volume_vs_avg_daily    = cumulative_volume / average_daily_volume          (None if avg missing/0)
    room_to_resistance_pct = (daily_resistance - price) / price                (None if unknown/none)

Optional session-volume check (disabled unless configured): cumulative_volume
is compared with min_premarket_cumulative_volume when open_price is None
(before the regular-session open), otherwise with min_cumulative_volume.

volume_vs_avg_daily is NOT conventional time-of-day relative volume (RVOL).
It compares PARTIAL session volume to an average FULL-DAY volume, so it can
substantially understate unusual volume early in the session. A separate
relative_volume_tod metric will be added when intraday volume history exists.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.market import Catalyst, CatalystType, ScannerSnapshot
from core.symbols import MAX_TICKER_LENGTH, TICKER_PATTERN
from strategy.in_play_config import InPlayConfig, Level, is_number

# Relative tolerance for float noise at thresholds, e.g. (3.3 - 3.0) / 3.0 = 0.0999...95.
TOLERANCE = 1e-9


class CheckStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"  # input data missing


@dataclass(frozen=True)
class CheckResult:
    name: str
    level: Level
    status: CheckStatus
    actual: float | str | None
    threshold: float | str | None
    message: str


@dataclass(frozen=True)
class InPlayMetrics:
    pct_change: float
    gap_pct: float | None
    volume_vs_avg_daily: float | None
    room_to_resistance_pct: float | None


@dataclass(frozen=True)
class InPlayResult:
    qualified: bool  # every HARD check passed on valid data
    valid_data: bool
    reasons: tuple[str, ...]  # data errors, or HARD failures/unknowns
    warnings: tuple[str, ...]  # PREFERRED failures/unknowns, negative catalysts
    hard_checks: tuple[CheckResult, ...]
    quality_checks: tuple[CheckResult, ...]
    quality_passed: int
    quality_total: int
    metrics: InPlayMetrics | None  # None only when data is invalid
    snapshot: ScannerSnapshot | None  # raw input, preserved unchanged (None if not a snapshot)
    config: InPlayConfig

    @property
    def ticker(self) -> str | None:
        return self.snapshot.ticker if self.snapshot is not None else None

    @property
    def as_of(self) -> datetime | None:
        return self.snapshot.as_of if self.snapshot is not None else None


# --- Snapshot validation -----------------------------------------------------


def _positive(value) -> bool:
    return is_number(value) and math.isfinite(value) and value > 0


def _non_negative_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _validate_catalyst(c, errors: list[str]) -> None:
    if not isinstance(c, Catalyst):
        errors.append(f"catalyst must be a Catalyst or None, got {type(c).__name__}")
        return
    if not isinstance(c.present, bool):
        errors.append("catalyst.present must be a bool")
    if c.type is not None and not isinstance(c.type, CatalystType):
        errors.append("catalyst.type must be a CatalystType or None")
    if c.headline is not None and not isinstance(c.headline, str):
        errors.append("catalyst.headline must be a string or None")
    if not isinstance(c.source, str) or not c.source.strip():
        errors.append("catalyst.source must be a non-empty string")


def validate_snapshot(s) -> tuple[str, ...]:
    """Return every problem with the raw snapshot. Empty tuple means usable. Never raises."""
    if not isinstance(s, ScannerSnapshot):
        return (f"expected ScannerSnapshot, got {type(s).__name__}",)

    errors: list[str] = []
    if (not isinstance(s.ticker, str) or len(s.ticker) > MAX_TICKER_LENGTH
            or not TICKER_PATTERN.fullmatch(s.ticker)):
        errors.append(f"ticker {s.ticker!r} is malformed")
    if not isinstance(s.as_of, datetime) or s.as_of.tzinfo is None:
        errors.append("as_of must be a timezone-aware datetime")
    if not isinstance(s.source, str) or not s.source.strip():
        errors.append("source must be a non-empty string")

    for name in ("price", "previous_close"):
        if not _positive(getattr(s, name)):
            errors.append(f"{name} must be a positive number, got {getattr(s, name)!r}")
    for name in ("open_price", "daily_resistance"):
        value = getattr(s, name)
        if value is not None and not _positive(value):
            errors.append(f"{name} must be a positive number or None, got {value!r}")

    if not _non_negative_int(s.cumulative_volume):
        errors.append(f"cumulative_volume must be a whole number >= 0, got {s.cumulative_volume!r}")
    if s.premarket_volume is not None and not _non_negative_int(s.premarket_volume):
        errors.append(f"premarket_volume must be a whole number >= 0 or None, got {s.premarket_volume!r}")
    avg = s.average_daily_volume
    if avg is not None and not (is_number(avg) and math.isfinite(avg) and avg >= 0):
        errors.append(f"average_daily_volume must be a number >= 0 or None, got {avg!r}")
    fs = s.float_shares
    if fs is not None and not (_non_negative_int(fs) and fs > 0):
        errors.append(f"float_shares must be a positive whole number or None, got {fs!r}")

    if s.catalyst is not None:
        _validate_catalyst(s.catalyst, errors)
    if not isinstance(s.resistance_checked, bool):
        errors.append("resistance_checked must be a bool")
    elif not s.resistance_checked and s.daily_resistance is not None:
        errors.append("daily_resistance is set but resistance_checked is False")
    return tuple(errors)


# --- Metrics -----------------------------------------------------------------


def compute_metrics(s: ScannerSnapshot) -> InPlayMetrics:
    """Derive measurements from a validated snapshot."""
    pc = s.previous_close
    gap = (s.open_price - pc) / pc if s.open_price is not None else None
    avg = s.average_daily_volume
    vol_ratio = s.cumulative_volume / avg if avg else None
    room = (s.daily_resistance - s.price) / s.price if s.daily_resistance is not None else None
    return InPlayMetrics(
        pct_change=(s.price - pc) / pc,
        gap_pct=gap,
        volume_vs_avg_daily=vol_ratio,
        room_to_resistance_pct=room,
    )


# --- Checks ------------------------------------------------------------------


def _at_least(actual: float, threshold: float) -> bool:
    return actual >= threshold - abs(threshold) * TOLERANCE


def _at_most(actual: float, threshold: float) -> bool:
    return actual <= threshold + abs(threshold) * TOLERANCE


def _fmt(value, kind: str) -> str:
    if kind == "pct":
        return f"{value:+.1%}"
    if kind == "price":
        return f"${value:,.2f}"
    if kind == "ratio":
        return f"{value:.2f}x"
    return f"{value:,}"  # shares


def _threshold_check(name, level, actual, threshold, kind, label, at_least) -> CheckResult:
    op_ok, op_bad = (">=", "<") if at_least else ("<=", ">")
    if actual is None:
        return CheckResult(name, level, CheckStatus.UNKNOWN, None, threshold,
                           f"{label} unknown (required {op_ok} {_fmt(threshold, kind)})")
    passed = _at_least(actual, threshold) if at_least else _at_most(actual, threshold)
    op = op_ok if passed else op_bad
    status = CheckStatus.PASS if passed else CheckStatus.FAIL
    return CheckResult(name, level, status, actual, threshold,
                       f"{label} {_fmt(actual, kind)} {op} {'min' if at_least else 'max'} {_fmt(threshold, kind)}")


def _catalyst_check(s: ScannerSnapshot, level: Level) -> CheckResult:
    c = s.catalyst
    if c is None:
        return CheckResult("catalyst", level, CheckStatus.UNKNOWN, None, "present",
                           "catalyst unknown (not checked)")
    if not c.present:
        return CheckResult("catalyst", level, CheckStatus.FAIL, "none", "present",
                           f"no catalyst found (source: {c.source})")
    kind = c.type.value if c.type is not None else "unclassified"
    return CheckResult("catalyst", level, CheckStatus.PASS, kind, "present",
                       f"catalyst present: {kind} (source: {c.source})")


def _room_check(s: ScannerSnapshot, m: InPlayMetrics, level: Level, min_room: float) -> CheckResult:
    name = "room_to_resistance"
    if not s.resistance_checked:
        return CheckResult(name, level, CheckStatus.UNKNOWN, None, min_room,
                           f"daily resistance unknown (required room >= {min_room:.0%})")
    if s.daily_resistance is None:
        return CheckResult(name, level, CheckStatus.PASS, None, min_room,
                           "no known overhead resistance on the daily chart")
    room = m.room_to_resistance_pct
    passed = _at_least(room, min_room)
    return CheckResult(
        name, level, CheckStatus.PASS if passed else CheckStatus.FAIL, room, min_room,
        f"room to daily resistance ${s.daily_resistance:,.2f} is {room:.1%} "
        f"{'>=' if passed else '<'} min {min_room:.0%}",
    )


def _build_checks(s: ScannerSnapshot, m: InPlayMetrics, c: InPlayConfig) -> list[CheckResult]:
    hard, pref = Level.HARD, Level.PREFERRED
    checks: list[CheckResult] = []

    def add(name, level, actual, threshold, kind, label, at_least):
        if threshold is not None:
            checks.append(_threshold_check(name, level, actual, threshold, kind, label, at_least))

    add("min_price", hard, s.price, c.min_price, "price", "price", True)
    add("max_price", hard, s.price, c.max_price, "price", "price", False)
    add("min_pct_change", hard, m.pct_change, c.min_pct_change, "pct", "% change", True)
    add("min_volume_vs_avg_daily", hard, m.volume_vs_avg_daily, c.min_volume_vs_avg_daily,
        "ratio", "volume vs avg daily", True)
    if s.open_price is None:  # before the regular-session open
        add("min_premarket_cumulative_volume", hard, s.cumulative_volume,
            c.min_premarket_cumulative_volume, "shares", "premarket volume", True)
    else:
        add("min_cumulative_volume", hard, s.cumulative_volume, c.min_cumulative_volume,
            "shares", "session volume", True)
    add("max_float_shares", hard, s.float_shares, c.max_float_shares, "shares", "float", False)
    add("preferred_max_float_shares", pref, s.float_shares, c.preferred_max_float_shares,
        "shares", "float", False)
    add("preferred_volume_vs_avg_daily", pref, m.volume_vs_avg_daily, c.preferred_volume_vs_avg_daily,
        "ratio", "volume vs avg daily", True)
    if c.catalyst_level is not Level.OFF:
        checks.append(_catalyst_check(s, c.catalyst_level))
    if c.room_level is not Level.OFF:
        checks.append(_room_check(s, m, c.room_level, c.min_room_to_resistance_pct))
    return checks


# --- Public API --------------------------------------------------------------


def evaluate_in_play(snapshot, config: InPlayConfig) -> InPlayResult:
    """Evaluate one snapshot. Never raises for bad data (it is reported, not qualified).

    Raises TypeError if config is not an InPlayConfig: a programming error, not input.
    """
    if not isinstance(config, InPlayConfig):
        raise TypeError(f"config must be an InPlayConfig, got {type(config).__name__}")

    preserved = snapshot if isinstance(snapshot, ScannerSnapshot) else None
    errors = validate_snapshot(snapshot)
    if errors:
        return InPlayResult(False, False, errors, (), (), (), 0, 0, None, preserved, config)

    metrics = compute_metrics(snapshot)
    checks = _build_checks(snapshot, metrics, config)
    hard_checks = tuple(ch for ch in checks if ch.level is Level.HARD)
    quality_checks = tuple(ch for ch in checks if ch.level is Level.PREFERRED)

    reasons = tuple(ch.message for ch in hard_checks if ch.status is not CheckStatus.PASS)
    warnings = [ch.message for ch in quality_checks if ch.status is not CheckStatus.PASS]
    cat = snapshot.catalyst
    if cat is not None and cat.present and cat.type in config.negative_catalyst_types:
        warnings.append(f"negative catalyst: {cat.type.value}")

    return InPlayResult(
        qualified=not reasons,
        valid_data=True,
        reasons=reasons,
        warnings=tuple(warnings),
        hard_checks=hard_checks,
        quality_checks=quality_checks,
        quality_passed=sum(ch.status is CheckStatus.PASS for ch in quality_checks),
        quality_total=len(quality_checks),
        metrics=metrics,
        snapshot=snapshot,
        config=config,
    )


def evaluate_universe(snapshots, config: InPlayConfig) -> tuple[InPlayResult, ...]:
    """Evaluate every snapshot, in input order. Failures are kept for research."""
    if not isinstance(config, InPlayConfig):
        raise TypeError(f"config must be an InPlayConfig, got {type(config).__name__}")
    return tuple(evaluate_in_play(s, config) for s in snapshots)
