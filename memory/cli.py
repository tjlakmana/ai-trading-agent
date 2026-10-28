"""Inspect scanner history:  python -m memory <command>

    runs                         recent scan attempts (successes and failures)
    show RUN_ID [--status S]     one run: configs, freshness, rows by class
    ticker TICKER                every recorded observation of one stock
    replay RUN_ID [--set k=v]    re-run the in-play filter on stored snapshots

Read-only: nothing here writes to the database (replays are not stored).
RUN_ID may be a unique prefix of at least 6 characters.
"""

import argparse
import sys
import types
import typing
from dataclasses import fields, replace

from data.market_hours import to_us_eastern
from memory import serialize as ser
from memory.scan_store import REJECTED, RowSummary, RunSummary, ScanStore
from strategy.in_play_config import InPlayConfig, Level

STATUSES = ("QUALIFIED", "NEAR_MISS", "FILTERED_OUT", REJECTED)


def _num(value, fmt: str) -> str:
    return "-" if value is None else format(value, fmt)


def _et(value) -> str:
    return "-" if value is None else f"{to_us_eastern(value):%Y-%m-%d %H:%M %Z}"


def _runs_table(runs: tuple[RunSummary, ...]) -> list[str]:
    lines = [f"{'RUN':<10}{'STARTED (ET)':<22}{'PROFILE':<16}{'STATUS':<8}"
             f"{'ROWS':>6}{'QUAL':>6}{'NEAR':>6}{'FILT':>6}{'REJ':>5}  ERROR"]
    for r in runs:
        error = f"{r.error_type}: {r.error_message}" if r.status == "ERROR" else ""
        lines.append(f"{r.run_id[:8]:<10}{_et(r.started_at):<22}{r.profile_name:<16}{r.status:<8}"
                     f"{r.row_count:>6}{r.qualified_count:>6}{r.near_miss_count:>6}"
                     f"{r.filtered_out_count:>6}{r.rejected_count:>5}  {error}")
    return lines


def _row_line(r: RowSummary) -> str:
    return (f"  {r.ticker or '?':<7}{r.status:<14}{_num(r.price, '>8.2f')}{_num(r.pct_change, '>+9.1%')}"
            f"{_num(r.cumulative_volume, '>13,')}{_num(r.volume_vs_avg_daily, '>9.2f')}"
            f"{_num(r.float_shares, '>15,')}  {', '.join(r.failed_checks)}")


ROW_HEADER = (f"  {'TICKER':<7}{'CLASS':<14}{'PRICE':>8}{'%CHG':>9}{'VOLUME':>13}{'VOL/AVG':>9}"
              f"{'FLOAT':>15}  FAILED HARD CHECKS")


def _show(store: ScanStore, run_id: str, status: str | None) -> list[str]:
    run = store.get_run(run_id)
    lines = [
        f"run             {run.run_id}",
        f"profile         {run.profile_name}   status {run.status}   provider {run.provider}",
        f"started_at      {run.started_at.isoformat()}",
        f"fetched_at      {run.fetched_at.isoformat() if run.fetched_at else '- (no data received)'}"
        + (f"  ({run.session} session)" if run.session else ""),
        f"quote freshness {run.quote_freshness.value} (Finviz provides no quote timestamp)",
        f"screen          {run.screen_config}",
        f"payload sha256  {run.payload_sha256 or '-'}",
    ]
    if run.status == "ERROR":
        return lines + [f"error           {run.error_type}: {run.error_message}"]
    store.load_payload(run.run_id)  # verifies integrity before showing anything as recorded
    lines.append(f"counts          rows {run.row_count} | qualified {run.qualified_count} | near-miss "
                 f"{run.near_miss_count} | filtered out {run.filtered_out_count} | rejected {run.rejected_count}")
    rows = store.rows(run.run_id, status)
    order = {s: i for i, s in enumerate(STATUSES)}
    rows = sorted(rows, key=lambda r: (order[r.status], -(r.pct_change or 0)))
    return lines + ["", ROW_HEADER] + [_row_line(r) for r in rows]


def _coerce(name: str, text: str):
    """Parse a --set value using the InPlayConfig field's declared type."""
    field = next((f for f in fields(InPlayConfig) if f.name == name), None)
    if field is None or name == "negative_catalyst_types":
        raise ValueError(f"unknown or unsupported InPlayConfig field {name!r}")
    if text.lower() == "none":
        return None
    kinds = typing.get_args(field.type) if isinstance(field.type, types.UnionType) else (field.type,)
    if Level in kinds:
        return Level(text.upper())
    if int in kinds:
        return int(text.replace("_", ""))
    return float(text)


def _replay(store: ScanStore, run_id: str, sets: list[str]) -> list[str]:
    payload = store.load_payload(run_id)
    config = ser.in_play_config_from_dict(payload["in_play_config"])
    changes = {}
    for item in sets:
        name, sep, value = item.partition("=")
        if not sep:
            raise ValueError(f"--set expects name=value, got {item!r}")
        changes[name.strip()] = _coerce(name.strip(), value.strip())
    config = replace(config, **changes)
    items = store.replay(run_id, config)

    counts = {s: sum(1 for i in items if i.classification.scan_class.value == s) for s in STATUSES[:3]}
    changed = [i for i in items if i.classification.scan_class.value != i.original_status]
    lines = [
        f"replay of {run_id[:8]} with changes {changes or '(none: original config)'}",
        f"qualified {counts['QUALIFIED']} | near-miss {counts['NEAR_MISS']} | "
        f"filtered out {counts['FILTERED_OUT']} | changed class {len(changed)}",
    ]
    for i in changed:
        lines.append(f"  {i.ticker:<7}{i.original_status:>13} -> {i.classification.scan_class.value:<13}"
                     f"{', '.join(i.classification.failed_hard_checks)}")
    return lines


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m memory", description="Inspect scanner history (read-only).")
    sub = p.add_subparsers(dest="command", required=True)
    runs = sub.add_parser("runs", help="recent scan attempts")
    runs.add_argument("--limit", type=int, default=20)
    show = sub.add_parser("show", help="one run in detail")
    show.add_argument("run_id")
    show.add_argument("--status", choices=STATUSES)
    ticker = sub.add_parser("ticker", help="history of one stock")
    ticker.add_argument("ticker")
    ticker.add_argument("--limit", type=int, default=50)
    rp = sub.add_parser("replay", help="re-evaluate a run with different in-play settings")
    rp.add_argument("run_id")
    rp.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE",
                    help="override an InPlayConfig field, e.g. min_pct_change=0.2 (repeatable)")
    return p


def main(argv: list[str] | None = None, *, store: ScanStore | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        own = store is None
        store = ScanStore.open_default(read_only=True) if own else store
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}. Run a scan first: python -m data.finviz", file=sys.stderr)
        return 2
    try:
        if args.command == "runs":
            lines = _runs_table(store.list_runs(args.limit))
        elif args.command == "show":
            lines = _show(store, store.resolve_run_id(args.run_id), args.status)
        elif args.command == "ticker":
            obs = store.ticker_history(args.ticker, args.limit)
            lines = [f"{args.ticker}: {len(obs)} observation(s)", f"  {'STARTED (ET)':<22}{'PROFILE':<16}"
                     + ROW_HEADER.strip()]
            lines += [f"  {_et(o.started_at):<22}{o.profile_name:<16}" + _row_line(o.row).strip() for o in obs]
        else:
            lines = _replay(store, store.resolve_run_id(args.run_id), args.set)
    except (KeyError, ValueError) as exc:
        print(f"error: {exc.args[0] if exc.args else exc}", file=sys.stderr)
        return 2
    finally:
        if own:
            store.close()
    print("\n".join(lines))
    return 0
