"""Manual Finviz in-play scan:  python -m data.finviz [options]

Research and manual testing only. It fetches one screen, runs the
deterministic in-play filter, and prints the results. It places no orders and
cannot: data/ never imports bot/ or execution/. Output never includes the API
key or the request URL.
"""

import argparse
import sys

from data.finviz.client import FinvizClient
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizCredentialsError, FinvizError
from data.finviz.scan import FinvizCandidate, FinvizScan, run_in_play_scan
from data.market_hours import to_us_eastern
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
    p.add_argument("--tickers", default="",
                   help="comma-separated symbols to evaluate instead of the discovery filters")
    p.add_argument("--min-volume", type=_volume_threshold, default=DEFAULT_MIN_VOLUME,
                   help=f"regular-session min cumulative volume (default {DEFAULT_MIN_VOLUME:,}; 0 = off)")
    p.add_argument("--min-premarket-volume", type=_volume_threshold, default=None,
                   help="premarket min cumulative volume (default off)")
    p.add_argument("--show-all", action="store_true", help="also list stocks that did not qualify")
    p.add_argument("--verbose", action="store_true", help="print every warning")
    return p


def _num(value, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def _row(c: FinvizCandidate) -> str:
    s, m, r = c.record.snapshot, c.result.metrics, c.record
    return (f"{s.ticker:<7}{_num(s.price, '>8.2f')}{_num(m.pct_change, '>+9.1%')}"
            f"{_num(s.cumulative_volume, '>13,')}{_num(m.volume_vs_avg_daily, '>9.2f')}"
            f"{_num(s.float_shares, '>13,')}{_num(r.day_high, '>9.2f')}"
            f"{_num(r.vendor.relative_volume, '>9.2f')}{len(c.result.warnings) + len(r.warnings):>6}")


HEADER = (f"{'TICKER':<7}{'PRICE':>8}{'%CHG':>9}{'VOLUME':>13}{'VOL/AVG':>9}"
          f"{'FLOAT':>13}{'DAY HI':>9}{'FV RVOL':>9}{'WARN':>6}")


def render(scan: FinvizScan, *, show_all: bool = False, verbose: bool = False) -> str:
    et = to_us_eastern(scan.fetched_at)
    cfg = scan.in_play_config
    lines = [
        "Finviz Elite in-play scan - research only, no orders are placed",
        f"fetched_at      {scan.fetched_at.isoformat(timespec='seconds')} "
        f"({et:%H:%M %Z}, {scan.session.value} session)",
        f"quote freshness {scan.quote_freshness.value} (Finviz provides no quote timestamp)",
        f"discovery       {', '.join(scan.screen_config.filters) or '(none)'}"
        + (f"  tickers={','.join(scan.screen_config.tickers)}" if scan.screen_config.tickers else ""),
        f"min volume      regular={_num(cfg.min_cumulative_volume, ',')} "
        f"premarket={_num(cfg.min_premarket_cumulative_volume, ',')}",
        f"rows {len(scan.candidates) + len(scan.rejected)} | normalized {len(scan.candidates)} | "
        f"rejected rows {len(scan.rejected)} | qualified {len(scan.qualified)}",
        "",
        "QUALIFIED - proceed to the next strategy stage (NOT a trade signal)",
        "%CHG and VOL/AVG are our calculations; FV RVOL is Finviz's, discovery only.",
    ]
    qualified = sorted(scan.qualified, key=lambda c: c.result.metrics.pct_change, reverse=True)
    lines += ([HEADER] + [_row(c) for c in qualified]) if qualified else ["  (none)"]
    if verbose:
        for c in qualified:
            for w in c.result.warnings + c.record.warnings:
                lines.append(f"  {c.record.ticker}: {w}")

    if show_all and scan.not_qualified:
        lines += ["", "NOT QUALIFIED"]
        for c in scan.not_qualified:
            lines.append(f"  {c.record.ticker:<7}{'; '.join(c.result.reasons)}")
    if scan.rejected:
        lines += ["", "REJECTED ROWS (could not be normalized)"]
        for r in scan.rejected:
            lines.append(f"  row {r.row_number} {r.ticker or '?'}: {'; '.join(r.errors)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, *, client=None, clock=None) -> int:
    args = _parser().parse_args(argv)
    try:
        tickers = tuple(t.strip() for t in args.tickers.split(",") if t.strip())
        screen = FinvizScreenConfig(filters=() if tickers else FinvizScreenConfig().filters,
                                    tickers=tickers)
        in_play = InPlayConfig(min_cumulative_volume=args.min_volume,
                               min_premarket_cumulative_volume=args.min_premarket_volume)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    try:
        client = FinvizClient.from_env() if client is None else client
        kwargs = {} if clock is None else {"clock": clock}
        scan = run_in_play_scan(client, screen, in_play, **kwargs)
    except FinvizCredentialsError as exc:
        print(f"error: {exc}. Add it to .env (see .env.example).", file=sys.stderr)
        return 2
    except FinvizError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(render(scan, show_all=args.show_all, verbose=args.verbose))
    return 0
