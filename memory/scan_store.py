"""Append-only SQLite scanner history.

Tables (schema version 1):
    scan_runs      one row per scan attempt: success (OK) or failure (ERROR),
                   with the original screen + in-play configs, fetched_at,
                   quote freshness, counts, and the payload hash
    scan_rows      small index: one row per stock per run, with its class
                   (QUALIFIED / NEAR_MISS / FILTERED_OUT / REJECTED) and key numbers
    scan_payloads  the full audit copy per successful run: every FinvizRecord
                   (raw cells, vendor metrics, errors, warnings, snapshot) and
                   every InPlayResult (all checks), as gzip-compressed JSON

Guarantees:
- Append-only: triggers abort every UPDATE and DELETE. There is no pruning.
- Integrity: each payload's SHA-256 (of its canonical JSON) is stored on the
  run and verified on every load.
- No secrets: scan objects never hold the API key or URL, error messages are
  already key-safe, and any "auth=<value>" text is redacted before writing.
- Each record_* call is one transaction, so a future scheduler (for example,
  every 5 minutes) can call the same API. WAL mode allows reads during writes.

fetched_at is when we received the response. Finviz provides no quote
timestamp, so quote_freshness is stored as UNKNOWN, never as verified.
"""

import gzip
import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from data.finviz.config import FinvizScreenConfig
from data.finviz.parse import QuoteFreshness, SOURCE
from data.finviz.scan import FinvizScan
from memory import serialize as ser
from memory.classification import Classification, ScanClass, classify
from strategy.in_play import InPlayResult, evaluate_universe
from strategy.in_play_config import InPlayConfig

SCHEMA_VERSION = 1
PAYLOAD_FORMAT_VERSION = 1
PAYLOAD_ENCODING = "gzip+json"
DB_PATH_ENV_VAR = "MEMORY_DB_PATH"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_DB_PATH = "runtime/memory.db"
REJECTED = "REJECTED"  # scan_rows status for rows without a snapshot

_AUTH_VALUE = re.compile(r"(auth=)[^&\s\"'\\]+", re.IGNORECASE)

_SCHEMA = """
CREATE TABLE scan_runs (
    run_id              TEXT PRIMARY KEY,
    recorded_at         TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    fetched_at          TEXT,
    session             TEXT,
    quote_freshness     TEXT NOT NULL,
    provider            TEXT NOT NULL,
    profile_name        TEXT NOT NULL,
    screen_config_json  TEXT NOT NULL,
    in_play_config_json TEXT NOT NULL,
    status              TEXT NOT NULL CHECK (status IN ('OK', 'ERROR')),
    error_type          TEXT,
    error_message       TEXT,
    row_count           INTEGER NOT NULL,
    qualified_count     INTEGER NOT NULL,
    near_miss_count     INTEGER NOT NULL,
    filtered_out_count  INTEGER NOT NULL,
    rejected_count      INTEGER NOT NULL,
    payload_sha256      TEXT,
    schema_version      INTEGER NOT NULL,
    CHECK ((status = 'OK') = (fetched_at IS NOT NULL AND payload_sha256 IS NOT NULL))
);
CREATE INDEX scan_runs_started ON scan_runs (started_at);

CREATE TABLE scan_rows (
    run_id              TEXT NOT NULL REFERENCES scan_runs (run_id),
    row_number          INTEGER NOT NULL,
    ticker              TEXT,
    status              TEXT NOT NULL
                        CHECK (status IN ('QUALIFIED', 'NEAR_MISS', 'FILTERED_OUT', 'REJECTED')),
    hard_failures       INTEGER,
    failed_checks_json  TEXT NOT NULL,
    price               REAL,
    pct_change          REAL,
    cumulative_volume   INTEGER,
    volume_vs_avg_daily REAL,
    float_shares        INTEGER,
    PRIMARY KEY (run_id, row_number)
);
CREATE INDEX scan_rows_ticker ON scan_rows (ticker, run_id);

CREATE TABLE scan_payloads (
    run_id          TEXT PRIMARY KEY REFERENCES scan_runs (run_id),
    format_version  INTEGER NOT NULL,
    encoding        TEXT NOT NULL,
    payload         BLOB NOT NULL
);
""" + "".join(
    f"""
CREATE TRIGGER {table}_no_{op.lower()} BEFORE {op} ON {table}
BEGIN SELECT RAISE(ABORT, 'scanner history is append-only'); END;
"""
    for table in ("scan_runs", "scan_rows", "scan_payloads")
    for op in ("UPDATE", "DELETE")
)


class HistoryIntegrityError(Exception):
    """A stored payload does not match its recorded SHA-256."""


class PayloadCache:
    """Thread-safe LRU cache of verified, decoded payloads.

    Safe because history is append-only: a run's payload never changes.
    Entries are keyed by (run_id, payload_sha256) and only added after the
    hash has been verified. Share one instance across short-lived stores
    (for example, one store per API request).
    """

    def __init__(self, max_runs: int = 4):
        if not isinstance(max_runs, int) or max_runs < 1:
            raise ValueError("max_runs must be a positive whole number")
        self._max = max_runs
        self._items: OrderedDict[tuple[str, str], dict] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple[str, str]) -> dict | None:
        with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    def put(self, key: tuple[str, str], value: dict) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    recorded_at: datetime
    started_at: datetime
    fetched_at: datetime | None  # None for failed attempts
    session: str | None
    quote_freshness: QuoteFreshness
    provider: str
    profile_name: str
    screen_config: dict
    in_play_config: dict
    status: str  # OK | ERROR
    error_type: str | None
    error_message: str | None
    row_count: int
    qualified_count: int
    near_miss_count: int
    filtered_out_count: int
    rejected_count: int
    payload_sha256: str | None
    schema_version: int


@dataclass(frozen=True)
class RowSummary:
    run_id: str
    row_number: int
    ticker: str | None
    status: str  # a ScanClass value, or REJECTED
    hard_failures: int | None
    failed_checks: tuple[str, ...]
    price: float | None
    pct_change: float | None  # our calculation, not Finviz's
    cumulative_volume: int | None
    volume_vs_avg_daily: float | None
    float_shares: int | None


@dataclass(frozen=True)
class TickerObservation:
    started_at: datetime
    profile_name: str
    row: RowSummary


@dataclass(frozen=True)
class ReplayItem:
    row_number: int
    ticker: str
    result: InPlayResult  # freshly computed from the stored snapshot
    classification: Classification
    original_status: str  # class recorded at scan time


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware datetimes")
    return value.astimezone(timezone.utc).isoformat()


def redact(text: str) -> str:
    """Mask any auth=<value> fragment. Defensive: nothing should contain one."""
    return _AUTH_VALUE.sub(r"\1***", text)


def _dumps(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False)


def default_db_path(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> Path:
    """MEMORY_DB_PATH from the environment, then .env, else runtime/memory.db.

    Relative paths are resolved against the project root.
    """
    environ = os.environ if environ is None else environ
    env_file = DEFAULT_ENV_FILE if env_file is None else Path(env_file)
    value = (environ.get(DB_PATH_ENV_VAR) or "").strip()
    if not value and env_file.is_file():
        value = (dotenv_values(env_file).get(DB_PATH_ENV_VAR) or "").strip()
    path = Path(value or DEFAULT_DB_PATH)
    return path if path.is_absolute() else PROJECT_ROOT / path


class ScanStore:
    def __init__(self, path: Path | str, *, read_only: bool = False,
                 clock: Callable[[], datetime] = _utc_now,
                 payload_cache: PayloadCache | None = None):
        self.path = Path(path)
        self._clock = clock
        self._cache = payload_cache
        if read_only:
            if not self.path.is_file():
                raise FileNotFoundError(f"no scanner history at {self.path}")
            self._conn = sqlite3.connect(f"{self.path.resolve().as_uri()}?mode=ro", uri=True, timeout=5.0)
        else:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, timeout=5.0)
            self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.row_factory = sqlite3.Row
        self._migrate(read_only)

    @classmethod
    def open_default(cls, *, read_only: bool = False, **kwargs) -> "ScanStore":
        return cls(default_db_path(), read_only=read_only, **kwargs)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ScanStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _migrate(self, read_only: bool) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f"{self.path} has schema version {version}; this code supports {SCHEMA_VERSION}")
        if version == SCHEMA_VERSION:
            return
        if read_only:
            raise RuntimeError(f"{self.path} is not an initialized scanner history database")
        # One script, one transaction: a crash leaves either no schema or all of it.
        self._conn.executescript(f"BEGIN; {_SCHEMA} PRAGMA user_version = {SCHEMA_VERSION}; COMMIT;")

    # --- Writes --------------------------------------------------------------

    def record_scan(self, scan: FinvizScan, profile_name: str, *,
                    started_at: datetime | None = None) -> str:
        """Record a successful scan: every candidate, every rejected row, all checks."""
        if not isinstance(scan, FinvizScan):
            raise TypeError(f"expected FinvizScan, got {type(scan).__name__}")
        _require_profile(profile_name)
        run_id = uuid.uuid4().hex
        classified = [(c, classify(c.result)) for c in scan.candidates]

        payload = {
            "format_version": PAYLOAD_FORMAT_VERSION,
            "run_id": run_id,
            "provider": SOURCE,
            "profile_name": profile_name,
            "fetched_at": ser.datetime_to_str(scan.fetched_at),
            "quote_freshness": scan.quote_freshness.value,
            "session": scan.session.value,
            "screen_config": ser.screen_config_to_dict(scan.screen_config),
            "in_play_config": ser.in_play_config_to_dict(scan.in_play_config),
            "candidates": [
                {"record": ser.record_to_dict(c.record), "result": ser.result_to_dict(c.result),
                 "classification": k.scan_class.value}
                for c, k in classified
            ],
            "rejected": [ser.record_to_dict(r) for r in scan.rejected],
        }
        canonical = redact(_dumps(payload)).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        counts = {k: sum(1 for _, c in classified if c.scan_class is k) for k in ScanClass}

        rows = [self._candidate_row(run_id, c, k) for c, k in classified]
        rows += [(run_id, r.row_number, r.ticker, REJECTED, None, "[]",
                  None, None, None, None, None) for r in scan.rejected]
        with self._conn:
            self._insert_run(
                run_id=run_id, started_at=started_at or scan.fetched_at, fetched_at=scan.fetched_at,
                session=scan.session.value, quote_freshness=scan.quote_freshness,
                profile_name=profile_name, screen_config=scan.screen_config,
                in_play_config=scan.in_play_config, status="OK", error=None,
                row_count=len(scan.candidates) + len(scan.rejected),
                counts=counts, rejected_count=len(scan.rejected), payload_sha256=digest,
            )
            self._conn.executemany("INSERT INTO scan_rows VALUES (?,?,?,?,?,?,?,?,?,?,?)", rows)
            self._conn.execute(
                "INSERT INTO scan_payloads VALUES (?,?,?,?)",
                (run_id, PAYLOAD_FORMAT_VERSION, PAYLOAD_ENCODING, gzip.compress(canonical, mtime=0)),
            )
        return run_id

    def record_scan_failure(self, error: BaseException, screen_config: FinvizScreenConfig,
                            in_play_config: InPlayConfig, profile_name: str, *,
                            started_at: datetime) -> str:
        """Record a scan attempt that produced no data (API, network, or format failure)."""
        if not isinstance(error, BaseException):
            raise TypeError("error must be an exception")
        if not isinstance(screen_config, FinvizScreenConfig) or not isinstance(in_play_config, InPlayConfig):
            raise TypeError("screen_config and in_play_config must be the configs that were used")
        _require_profile(profile_name)
        run_id = uuid.uuid4().hex
        with self._conn:
            self._insert_run(
                run_id=run_id, started_at=started_at, fetched_at=None, session=None,
                quote_freshness=QuoteFreshness.UNKNOWN, profile_name=profile_name,
                screen_config=screen_config, in_play_config=in_play_config, status="ERROR",
                error=error, row_count=0, counts={k: 0 for k in ScanClass}, rejected_count=0,
                payload_sha256=None,
            )
        return run_id

    def _insert_run(self, *, run_id, started_at, fetched_at, session, quote_freshness, profile_name,
                    screen_config, in_play_config, status, error, row_count, counts,
                    rejected_count, payload_sha256) -> None:
        self._conn.execute(
            "INSERT INTO scan_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                run_id, _utc_text(self._clock()), _utc_text(started_at),
                _utc_text(fetched_at) if fetched_at is not None else None, session,
                quote_freshness.value, SOURCE, profile_name,
                redact(_dumps(ser.screen_config_to_dict(screen_config))),
                redact(_dumps(ser.in_play_config_to_dict(in_play_config))),
                status,
                type(error).__name__ if error is not None else None,
                redact(str(error)) if error is not None else None,
                row_count, counts[ScanClass.QUALIFIED], counts[ScanClass.NEAR_MISS],
                counts[ScanClass.FILTERED_OUT], rejected_count, payload_sha256, SCHEMA_VERSION,
            ),
        )

    @staticmethod
    def _candidate_row(run_id: str, candidate, k: Classification) -> tuple:
        s, m = candidate.record.snapshot, candidate.result.metrics
        return (
            run_id, candidate.record.row_number, candidate.record.ticker, k.scan_class.value,
            k.hard_failures, _dumps(list(k.failed_hard_checks)),
            s.price, m.pct_change if m is not None else None, s.cumulative_volume,
            m.volume_vs_avg_daily if m is not None else None, s.float_shares,
        )

    # --- Reads ---------------------------------------------------------------

    def resolve_run_id(self, prefix: str) -> str:
        """Full run id from a unique prefix (at least 6 characters)."""
        if not isinstance(prefix, str) or len(prefix) < 6 or not prefix.isalnum():
            raise ValueError("run id prefix must be at least 6 letters/digits")
        rows = self._conn.execute("SELECT run_id FROM scan_runs WHERE run_id LIKE ? LIMIT 2",
                                  (prefix.lower() + "%",)).fetchall()
        if len(rows) != 1:
            raise KeyError(f"no unique scan run matches {prefix!r}")
        return rows[0]["run_id"]

    def list_runs(self, limit: int = 20, *, profile: str | None = None, status: str | None = None,
                  before: datetime | None = None) -> tuple[RunSummary, ...]:
        """Most recent first, optionally filtered by profile, status (OK/ERROR) and start time."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ValueError("limit must be a whole number from 1 to 1000")
        clauses, args = [], []
        if profile is not None:
            clauses.append("profile_name = ?")
            args.append(profile)
        if status is not None:
            if status not in ("OK", "ERROR"):
                raise ValueError("status must be OK or ERROR")
            clauses.append("status = ?")
            args.append(status)
        if before is not None:
            clauses.append("started_at < ?")
            args.append(_utc_text(before))
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        rows = self._conn.execute(
            f"SELECT * FROM scan_runs {where}ORDER BY started_at DESC, recorded_at DESC LIMIT ?",
            (*args, limit)).fetchall()
        return tuple(_run_summary(r) for r in rows)

    def latest_run(self, profile: str | None = None) -> RunSummary | None:
        """The most recent successful run (optionally for one profile), or None."""
        runs = self.list_runs(1, profile=profile, status="OK")
        return runs[0] if runs else None

    def get_run(self, run_id: str) -> RunSummary:
        row = self._conn.execute("SELECT * FROM scan_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"no scan run {run_id!r}")
        return _run_summary(row)

    def rows(self, run_id: str, status: str | None = None) -> tuple[RowSummary, ...]:
        sql, args = "SELECT * FROM scan_rows WHERE run_id = ?", [run_id]
        if status is not None:
            sql, args = sql + " AND status = ?", args + [status]
        return tuple(_row_summary(r) for r in self._conn.execute(sql + " ORDER BY row_number", args))

    def ticker_history(self, ticker: str, limit: int = 50) -> tuple[TickerObservation, ...]:
        """Every recorded observation of one ticker, most recent first."""
        rows = self._conn.execute(
            "SELECT r.*, s.started_at AS run_started_at, s.profile_name AS run_profile "
            "FROM scan_rows r JOIN scan_runs s USING (run_id) "
            "WHERE r.ticker = ? ORDER BY s.started_at DESC LIMIT ?", (ticker, limit)).fetchall()
        return tuple(TickerObservation(ser.datetime_from_str(r["run_started_at"]), r["run_profile"],
                                       _row_summary(r)) for r in rows)

    def load_payload(self, run_id: str) -> dict:
        """The full audit record of a successful run, verified against its SHA-256."""
        run = self.get_run(run_id)
        if run.status != "OK":
            raise ValueError(f"scan run {run_id} failed ({run.error_type}); it has no payload")
        row = self._conn.execute("SELECT * FROM scan_payloads WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise HistoryIntegrityError(f"payload for scan run {run_id} is missing")
        if row["format_version"] != PAYLOAD_FORMAT_VERSION or row["encoding"] != PAYLOAD_ENCODING:
            raise ValueError(f"unsupported payload format {row['format_version']}/{row['encoding']}")
        key = (run_id, run.payload_sha256)
        if self._cache is not None:
            cached = self._cache.get(key)
            if cached is not None:
                return cached
        canonical = gzip.decompress(row["payload"])
        if hashlib.sha256(canonical).hexdigest() != run.payload_sha256:
            raise HistoryIntegrityError(f"payload for scan run {run_id} does not match its SHA-256")
        payload = json.loads(canonical)
        if self._cache is not None:
            self._cache.put(key, payload)
        return payload

    def get_entry(self, run_id: str, row_number: int) -> dict:
        """One stock's full audit entry from a run's payload.

        Returns {"kind": "candidate", "record", "result", "classification"} or
        {"kind": "rejected", "record"}. Raises KeyError if the row is not in the run.
        Treat the returned dicts as read-only: they may be shared through the cache.
        """
        payload = self.load_payload(run_id)
        for c in payload["candidates"]:
            if c["record"]["row_number"] == row_number:
                return {"kind": "candidate", **c}
        for r in payload["rejected"]:
            if r["row_number"] == row_number:
                return {"kind": "rejected", "record": r}
        raise KeyError(f"scan run {run_id} has no row {row_number}")

    def replay(self, run_id: str, in_play_config: InPlayConfig | None = None) -> tuple[ReplayItem, ...]:
        """Re-run the deterministic in-play filter on the stored snapshots.

        With no config, the run's original config is used, which reproduces the
        recorded results. Read-only: replays are never written back.
        """
        payload = self.load_payload(run_id)
        config = (ser.in_play_config_from_dict(payload["in_play_config"])
                  if in_play_config is None else in_play_config)
        if not isinstance(config, InPlayConfig):
            raise TypeError(f"in_play_config must be an InPlayConfig, got {type(config).__name__}")
        candidates = payload["candidates"]
        snapshots = [ser.snapshot_from_dict(c["record"]["snapshot"]) for c in candidates]
        results = evaluate_universe(snapshots, config)
        return tuple(
            ReplayItem(c["record"]["row_number"], c["record"]["ticker"], res, classify(res), c["classification"])
            for c, res in zip(candidates, results)
        )


def _require_profile(profile_name) -> None:
    if not isinstance(profile_name, str) or not profile_name.strip():
        raise ValueError("profile_name must be a non-empty string")


def _run_summary(r: sqlite3.Row) -> RunSummary:
    return RunSummary(
        run_id=r["run_id"], recorded_at=ser.datetime_from_str(r["recorded_at"]),
        started_at=ser.datetime_from_str(r["started_at"]), fetched_at=ser.datetime_from_str(r["fetched_at"]),
        session=r["session"], quote_freshness=QuoteFreshness(r["quote_freshness"]), provider=r["provider"],
        profile_name=r["profile_name"], screen_config=json.loads(r["screen_config_json"]),
        in_play_config=json.loads(r["in_play_config_json"]), status=r["status"],
        error_type=r["error_type"], error_message=r["error_message"], row_count=r["row_count"],
        qualified_count=r["qualified_count"], near_miss_count=r["near_miss_count"],
        filtered_out_count=r["filtered_out_count"], rejected_count=r["rejected_count"],
        payload_sha256=r["payload_sha256"], schema_version=r["schema_version"],
    )


def _row_summary(r: sqlite3.Row) -> RowSummary:
    return RowSummary(
        run_id=r["run_id"], row_number=r["row_number"], ticker=r["ticker"], status=r["status"],
        hard_failures=r["hard_failures"], failed_checks=tuple(json.loads(r["failed_checks_json"])),
        price=r["price"], pct_change=r["pct_change"], cumulative_volume=r["cumulative_volume"],
        volume_vs_avg_daily=r["volume_vs_avg_daily"], float_shares=r["float_shares"],
    )
