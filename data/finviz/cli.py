"""Manual Finviz in-play scan:  python -m data.finviz [options]

Research and manual testing only. It fetches one screen, runs the
deterministic in-play filter, prints the results, and records the attempt
(success or failure) in scanner history (memory/, MEMORY_DB_PATH) unless
--no-record is given. It places no orders and cannot: data/ never imports
bot/ or execution/. Output never includes the API key or the request URL.
"""

import argparse
import sys
from datetime import datetime, timezone

from data.finviz.client import FinvizClient
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizCredentialsError, FinvizError
from data.finviz.profiles import CUSTOM_TICKERS, DEFAULT_PROFILE, PROFILES
from data.finviz.scan import FinvizCandidate, FinvizScan, run_in_play_scan
from data.market_hours import to_us_eastern
from memory.classification import ScanClass, classify
from memory.scan_store import ScanStore
from strategy.in_play_config import InPlayConfig

DEFAULT_MIN_VOLUME = 500_000  # V1 starting hypothesis, adjustable with --min-volume


def _volume_threshold(text: str) -> int | None:
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError("must be >= 0 (0 disables the check)")
    return value or None


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m data.finviz",
                                description="Finviz discovery + deterministic in-play filter. No orders.")
    p.add_argument("--profile", choices=sorted(PROFILES), default=DEFAULT_PROFILE,
                   help=f"discovery profile (default {DEFAULT_PROFILE}; broad_v1 = price $2-$20 and up)")
    p.add_argument("--tickers", default="",
                   help="comma-separated symbols to evaluate instead of a discovery profile")
    p.add_argument("--min-volume", type=_volume_threshold, default=DEFAULT_MIN_VOLUME,
                   help=f"regular-session min cumulative volume (default {DEFAULT_MIN_VOLUME:,}; 0 = off)")
    p.add_argument("--min-premarket-volume", type=_volume_threshold, default=None,
                   help="premarket min cumulative volume (default off)")
    p.add_argument("--show-near-miss", action="store_true",
                   help="also list near-misses (exactly one HARD check did not pass)")
    p.add_argument("--show-all", action="store_true",
                   help="also list every stock that did not qualify, near-misses included, with reasons")
    p.add_argument("--verbose", action="store_true", help="print every warning")
    p.add_argument("--no-record", action="store_true", help="do not write this scan to scanner history")
    return p


def _num(value, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def _row(c: FinvizCandidate) -> str:
    s, m, r = c.record.snapshot, c.result.metrics, c.record
    return (f"{s.ticker:<7}{_num(s.price, '>8.2f')}{_num(m.pct_change, '>+9.1%')}"
            f"{_num(s.cumulative_volume, '>13,')}{_num(m.volume_vs_avg_daily, '>9.2f')}"
            f"{_num(s.float_shares, '>15,')}{_num(r.day_high, '>9.2f')}"
            f"{_num(r.vendor.relative_volume, '>9.2f')}{len(c.result.warnings) + len(r.warnings):>6}")


HEADER = (f"{'TICKER':<7}{'PRICE':>8}{'%CHG':>9}{'VOLUME':>13}{'VOL/AVG':>9}"
          f"{'FLOAT':>15}{'DAY HI':>9}{'FV RVOL':>9}{'WARN':>6}")


def _by_change(candidates) -> list[FinvizCandidate]:
    return sorted(candidates, key=lambda c: c.result.metrics.pct_change if c.result.metrics else 0, reverse=True)


def render(scan: FinvizScan, *, profile_name: str = DEFAULT_PROFILE, show_near_miss: bool = False,
           show_all: bool = False, verbose: bool = False) -> str:
    et = to_us_eastern(scan.fetched_at)
    cfg = scan.in_play_config
    groups = {k: [] for k in ScanClass}
    for c in scan.candidates:
        groups[classify(c.result).scan_class].append(c)
    lines = [
        "Finviz Elite in-play scan - research only, no orders are placed",
        f"fetched_at      {scan.fetched_at.isoformat(timespec='seconds')} "
        f"({et:%H:%M %Z}, {scan.session.value} session)",
        f"quote freshness {scan.quote_freshness.value} (Finviz provides no quote timestamp)",
        f"profile         {profile_name}: {', '.join(scan.screen_config.filters) or '(no filters)'}"
        + (f"  tickers={','.join(scan.screen_config.tickers)}" if scan.screen_config.tickers else ""),
        f"min volume      regular={_num(cfg.min_cumulative_volume, ',')} "
        f"premarket={_num(cfg.min_premarket_cumulative_volume, ',')}",
        f"rows {len(scan.candidates) + len(scan.rejected)} | qualified {len(groups[ScanClass.QUALIFIED])} | "
        f"near-miss {len(groups[ScanClass.NEAR_MISS])} | filtered out {len(groups[ScanClass.FILTERED_OUT])} | "
        f"rejected rows {len(scan.rejected)}",
        "",
        "QUALIFIED - proceed to the next strategy stage (NOT a trade signal)",
        "%CHG and VOL/AVG are our calculations; FV RVOL is Finviz's, discovery only.",
    ]
    qualified = _by_change(groups[ScanClass.QUALIFIED])
    lines += ([HEADER] + [_row(c) for c in qualified]) if qualified else ["  (none)"]
    if verbose:
        for c in qualified:
            for w in c.result.warnings + c.record.warnings:
                lines.append(f"  {c.record.ticker}: {w}")

    near = _by_change(groups[ScanClass.NEAR_MISS])
    if show_all:
        listed = [(ScanClass.NEAR_MISS, c) for c in near]
        listed += [(ScanClass.FILTERED_OUT, c) for c in _by_change(groups[ScanClass.FILTERED_OUT])]
        if listed:
            lines += ["", "NOT QUALIFIED (near-miss = exactly one HARD check did not pass)"]
            lines += [f"  {c.record.ticker:<7}{k.value:<14}{'; '.join(c.result.reasons)}" for k, c in listed]
    elif show_near_miss and near:
        lines += ["", "NEAR MISS - exactly one HARD check did not pass (not a trade signal)"]
        lines += [f"  {c.record.ticker:<7}{'; '.join(c.result.reasons)}" for c in near]
    if scan.rejected:
        lines += ["", "REJECTED ROWS (could not be normalized)"]
        for r in scan.rejected:
            lines.append(f"  row {r.row_number} {r.ticker or '?'}: {'; '.join(r.errors)}")
    return "\n".join(lines)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def main(argv: list[str] | None = None, *, client=None, clock=None, store: ScanStore | None = None) -> int:
    args = _parser().parse_args(argv)
    clock = clock or _utc_now
    try:
        tickers = tuple(t.strip() for t in args.tickers.split(",") if t.strip())
        profile_name = CUSTOM_TICKERS if tickers else args.profile
        screen = FinvizScreenConfig(filters=(), tickers=tickers) if tickers else PROFILES[profile_name]
        in_play = InPlayConfig(min_cumulative_volume=args.min_volume,
                               min_premarket_cumulative_volume=args.min_premarket_volume)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    own_store = store is None and not args.no_record
    if own_store:
        store = ScanStore.open_default()
    try:
        started_at = clock()
        try:
            client = FinvizClient.from_env() if client is None else client
            scan = run_in_play_scan(client, screen, in_play, clock=clock)
        except FinvizError as exc:
            run_id = None
            if store is not None and not args.no_record:
                run_id = store.record_scan_failure(exc, screen, in_play, profile_name, started_at=started_at)
            hint = ". Add it to .env (see .env.example)" if isinstance(exc, FinvizCredentialsError) else ""
            print(f"error: {exc}{hint}", file=sys.stderr)
            if run_id:
                print(f"failed attempt recorded as run {run_id[:8]}", file=sys.stderr)
            return 2 if isinstance(exc, FinvizCredentialsError) else 1

        print(render(scan, profile_name=profile_name, show_near_miss=args.show_near_miss,
                     show_all=args.show_all, verbose=args.verbose))
        if store is not None and not args.no_record:
            run_id = store.record_scan(scan, profile_name, started_at=started_at)
            print(f"\nrecorded as run {run_id[:8]} in {store.path.name} "
                  f"(inspect: python -m memory show {run_id[:8]})")
        return 0
    finally:
        if own_store:
            store.close()
