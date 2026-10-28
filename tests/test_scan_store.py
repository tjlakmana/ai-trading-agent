"""Tests for memory/scan_store.py. Temporary SQLite databases and mocked scans only."""

import gzip
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from data.finviz import schema as col
from data.finviz.client import FinvizClient, SlidingWindowRateLimiter
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizAuthError, FinvizNetworkError
from data.finviz.parse import QuoteFreshness
from data.finviz.scan import run_in_play_scan
from memory import scan_store as ss
from memory import serialize as ser
from memory.scan_store import HistoryIntegrityError, ScanStore, default_db_path
from strategy.in_play_config import InPlayConfig
from tests.finviz_fixtures import (
    FAKE_KEY,
    T_PREMARKET,
    T_REGULAR,
    FakeClient,
    FakeClock,
    FakeResponse,
    FakeSession,
    csv_text,
    row,
)

QUALIFIES = row()  # ABCD
NEAR_MISS = row({col.TICKER: "EFGH", col.PRICE: "5.20"})  # only % change fails
FILTERED = row({col.TICKER: "IJKL", col.PRICE: "5.20", col.SHARES_FLOAT: "50.00"})  # two HARD failures
REJECTED = row({col.TICKER: "MNOP", col.PREV_CLOSE: "-"})  # cannot be normalized
STARTED = T_REGULAR - timedelta(seconds=2)


def make_scan(*rows, at=T_REGULAR, in_play=None, screen=None):
    return run_in_play_scan(FakeClient(csv_text(*rows)), screen, in_play, clock=lambda: at)


@pytest.fixture
def store(tmp_path):
    with ScanStore(tmp_path / "memory.db", clock=lambda: T_REGULAR + timedelta(seconds=1)) as s:
        yield s


@pytest.fixture
def run_id(store):
    scan = make_scan(QUALIFIES, NEAR_MISS, FILTERED, REJECTED, in_play=InPlayConfig(min_cumulative_volume=500_000))
    return store.record_scan(scan, "broad_v1", started_at=STARTED)


# --- Schema ------------------------------------------------------------------


def test_new_database_has_schema_v1(store):
    conn = sqlite3.connect(store.path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == ss.SCHEMA_VERSION == 1
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"scan_runs", "scan_rows", "scan_payloads"} <= tables
    conn.close()


def test_reopening_keeps_history(tmp_path):
    path = tmp_path / "memory.db"
    with ScanStore(path) as s:
        rid = s.record_scan(make_scan(QUALIFIES), "strict_v1")
    with ScanStore(path) as s:
        assert [r.run_id for r in s.list_runs()] == [rid]


def test_newer_schema_is_refused(tmp_path):
    path = tmp_path / "memory.db"
    ScanStore(path).close()
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RuntimeError, match="schema version 99"):
        ScanStore(path)


def test_read_only_requires_existing_database(tmp_path):
    with pytest.raises(FileNotFoundError):
        ScanStore(tmp_path / "missing.db", read_only=True)
    assert not (tmp_path / "missing.db").exists()


def test_read_only_refuses_writes(tmp_path, run_id, store):
    with ScanStore(store.path, read_only=True) as ro:
        assert ro.get_run(run_id).status == "OK"
        with pytest.raises(sqlite3.OperationalError):
            ro.record_scan(make_scan(QUALIFIES), "strict_v1")


def test_creates_parent_directory(tmp_path):
    with ScanStore(tmp_path / "runtime" / "nested" / "memory.db") as s:
        assert s.path.parent.is_dir()


# --- Successful scans --------------------------------------------------------


def test_run_summary(store, run_id):
    run = store.get_run(run_id)
    assert run.status == "OK" and run.error_type is None
    assert run.profile_name == "broad_v1" and run.provider == "finviz_elite"
    assert run.started_at == STARTED
    assert run.fetched_at == T_REGULAR  # kept separate from started_at and recorded_at
    assert run.recorded_at == T_REGULAR + timedelta(seconds=1)
    assert run.quote_freshness is QuoteFreshness.UNKNOWN
    assert run.session == "REGULAR"
    assert (run.row_count, run.qualified_count, run.near_miss_count,
            run.filtered_out_count, run.rejected_count) == (4, 1, 1, 1, 1)
    assert len(run.payload_sha256) == 64
    assert run.schema_version == 1


def test_original_configs_are_saved(store, run_id):
    run = store.get_run(run_id)
    assert run.screen_config == ser.screen_config_to_dict(FinvizScreenConfig())
    assert ser.in_play_config_from_dict(run.in_play_config) == InPlayConfig(min_cumulative_volume=500_000)


def test_rows_are_indexed_by_class(store, run_id):
    rows = {r.ticker: r for r in store.rows(run_id)}
    assert {t: r.status for t, r in rows.items()} == {
        "ABCD": "QUALIFIED", "EFGH": "NEAR_MISS", "IJKL": "FILTERED_OUT", "MNOP": "REJECTED"}
    assert rows["EFGH"].failed_checks == ("min_pct_change",)
    assert rows["IJKL"].hard_failures == 2
    assert rows["ABCD"].pct_change == pytest.approx(0.30)  # our calculation
    assert rows["ABCD"].float_shares == 6_000_000
    assert rows["MNOP"].price is None and rows["MNOP"].hard_failures is None
    assert [r.ticker for r in store.rows(run_id, "NEAR_MISS")] == ["EFGH"]


def test_payload_keeps_everything(store, run_id):
    p = store.load_payload(run_id)
    assert p["fetched_at"] == T_REGULAR.isoformat() and p["quote_freshness"] == "UNKNOWN"
    assert [c["record"]["ticker"] for c in p["candidates"]] == ["ABCD", "EFGH", "IJKL"]
    assert [c["classification"] for c in p["candidates"]] == ["QUALIFIED", "NEAR_MISS", "FILTERED_OUT"]
    rejected = p["rejected"][0]
    assert rejected["ticker"] == "MNOP" and rejected["errors"] == ["Prev Close is missing"]
    assert rejected["raw"][col.PREV_CLOSE] == "-"  # raw cells kept unchanged
    abcd = p["candidates"][0]
    assert abcd["record"]["raw"] == QUALIFIES
    assert abcd["record"]["quote_time"] is None
    names = {c["name"] for c in abcd["result"]["hard_checks"]}
    assert "min_cumulative_volume" in names and "max_float_shares" in names
    assert abcd["result"]["quality_checks"]  # PREFERRED checks too


def test_payload_is_compressed(store, run_id):
    blob = sqlite3.connect(store.path).execute("SELECT payload FROM scan_payloads").fetchone()[0]
    assert gzip.decompress(blob).startswith(b"{")


def test_started_at_defaults_to_fetched_at(store):
    rid = store.record_scan(make_scan(QUALIFIES), "strict_v1")
    assert store.get_run(rid).started_at == T_REGULAR


def test_premarket_session_is_recorded(store):
    rid = store.record_scan(make_scan(QUALIFIES, at=T_PREMARKET), "strict_v1")
    assert store.get_run(rid).session == "PREMARKET"
    assert store.load_payload(rid)["candidates"][0]["record"]["snapshot"]["open_price"] is None


def test_empty_scan_is_recorded(store):
    rid = store.record_scan(make_scan(), "strict_v1")
    assert store.get_run(rid).row_count == 0 and store.rows(rid) == ()


@pytest.mark.parametrize("name", ["", "  ", None])
def test_profile_name_required(store, name):
    with pytest.raises(ValueError):
        store.record_scan(make_scan(QUALIFIES), name)


def test_record_scan_requires_scan(store):
    with pytest.raises(TypeError):
        store.record_scan({"candidates": []}, "strict_v1")


# --- Failed attempts ---------------------------------------------------------


def test_failed_attempt_is_recorded(store):
    rid = store.record_scan_failure(FinvizAuthError("Finviz rejected the API key (HTTP 401)"),
                                    FinvizScreenConfig(), InPlayConfig(), "strict_v1", started_at=STARTED)
    run = store.get_run(rid)
    assert run.status == "ERROR"
    assert (run.error_type, run.error_message) == ("FinvizAuthError", "Finviz rejected the API key (HTTP 401)")
    assert run.fetched_at is None and run.session is None and run.payload_sha256 is None
    assert run.quote_freshness is QuoteFreshness.UNKNOWN
    assert run.row_count == 0 and store.rows(rid) == ()
    assert ser.in_play_config_from_dict(run.in_play_config) == InPlayConfig()
    with pytest.raises(ValueError, match="has no payload"):
        store.load_payload(rid)
    with pytest.raises(ValueError):
        store.replay(rid)


def test_failure_requires_the_configs_used(store):
    with pytest.raises(TypeError):
        store.record_scan_failure(FinvizNetworkError("x"), None, InPlayConfig(), "strict_v1", started_at=STARTED)


def test_failures_and_successes_listed_together(store, run_id):
    store.record_scan_failure(FinvizNetworkError("timed out"), FinvizScreenConfig(), InPlayConfig(),
                              "strict_v1", started_at=T_REGULAR + timedelta(minutes=5))
    assert [r.status for r in store.list_runs()] == ["ERROR", "OK"]  # most recent first


# --- Append-only and integrity -----------------------------------------------


@pytest.mark.parametrize("sql", [
    "UPDATE scan_runs SET qualified_count = 99",
    "DELETE FROM scan_runs",
    "UPDATE scan_rows SET status = 'QUALIFIED'",
    "DELETE FROM scan_rows",
    "UPDATE scan_payloads SET payload = x'00'",
    "DELETE FROM scan_payloads",
])
def test_history_is_append_only(store, run_id, sql):
    conn = sqlite3.connect(store.path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(sql)
    conn.close()


def test_tampered_payload_is_detected(store, run_id):
    # Someone with raw file access removes the trigger and rewrites the payload.
    conn = sqlite3.connect(store.path)
    conn.execute("DROP TRIGGER scan_payloads_no_update")
    conn.execute("UPDATE scan_payloads SET payload = ?", (gzip.compress(b'{"candidates": []}'),))
    conn.commit()
    conn.close()
    with pytest.raises(HistoryIntegrityError, match="SHA-256"):
        store.load_payload(run_id)


def test_ok_run_requires_payload_hash(store):
    conn = sqlite3.connect(store.path)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO scan_runs VALUES ('x','t','t',NULL,NULL,'UNKNOWN','finviz_elite','p',"
                     "'{}','{}','OK',NULL,NULL,0,0,0,0,0,NULL,1)")
    conn.close()


# --- Replay ------------------------------------------------------------------


def test_replay_with_original_config_reproduces_results(store, run_id):
    payload = store.load_payload(run_id)
    items = store.replay(run_id)
    assert [ser.result_to_dict(i.result) for i in items] == [c["result"] for c in payload["candidates"]]
    assert all(i.classification.scan_class.value == i.original_status for i in items)


def test_replay_with_different_config(store, run_id):
    items = {i.ticker: i for i in store.replay(run_id, InPlayConfig(min_pct_change=0.02))}
    assert items["EFGH"].original_status == "NEAR_MISS"
    assert items["EFGH"].classification.scan_class.value == "QUALIFIED"  # +4% passes a +2% minimum
    assert items["IJKL"].classification.scan_class.value == "NEAR_MISS"  # now only float fails


def test_replay_is_deterministic_and_never_written(store, run_id):
    config = InPlayConfig(max_float_shares=5_000_000, preferred_max_float_shares=None)
    first = [ser.result_to_dict(i.result) for i in store.replay(run_id, config)]
    second = [ser.result_to_dict(i.result) for i in store.replay(run_id, config)]
    assert first == second
    assert len(store.list_runs()) == 1 and store.get_run(run_id).qualified_count == 1


def test_replay_uses_stored_snapshots_not_vendor_values(store):
    rid = store.record_scan(make_scan(row({col.CHANGE: "-50.00%", col.RELATIVE_VOLUME: "0.01"})), "strict_v1")
    (item,) = store.replay(rid)
    assert item.result.metrics.pct_change == pytest.approx(0.30)


def test_replay_requires_config(store, run_id):
    with pytest.raises(TypeError):
        store.replay(run_id, {"min_price": 1})


# --- Reads -------------------------------------------------------------------


def test_ticker_history_across_runs(store):
    first = store.record_scan(make_scan(QUALIFIES), "strict_v1", started_at=T_REGULAR)
    later = T_REGULAR + timedelta(minutes=5)
    second = store.record_scan(make_scan(row({col.PRICE: "5.20"}), at=later), "broad_v1", started_at=later)
    obs = store.ticker_history("ABCD")
    assert [(o.row.run_id, o.row.status, o.profile_name) for o in obs] == [
        (second, "NEAR_MISS", "broad_v1"), (first, "QUALIFIED", "strict_v1")]
    assert store.ticker_history("ZZZZ") == ()


def test_list_runs_limit_and_order(store):
    ids = [store.record_scan(make_scan(QUALIFIES), "strict_v1", started_at=T_REGULAR + timedelta(minutes=i))
           for i in range(3)]
    assert [r.run_id for r in store.list_runs(limit=2)] == [ids[2], ids[1]]


def test_resolve_run_id(store, run_id):
    assert store.resolve_run_id(run_id[:8]) == run_id
    assert store.resolve_run_id(run_id[:8].upper()) == run_id
    with pytest.raises(ValueError):
        store.resolve_run_id(run_id[:3])
    with pytest.raises(ValueError):
        store.resolve_run_id("abc%25'--")
    with pytest.raises(KeyError):
        store.resolve_run_id("ffffffffff")


def test_get_unknown_run(store):
    with pytest.raises(KeyError):
        store.get_run("nope")


def test_larger_scan_round_trip(store):
    rows = [row({col.TICKER: f"T{i:03d}", col.PRICE: f"{2 + i % 18}.10"}) for i in range(1000)]
    rid = store.record_scan(make_scan(*rows), "broad_v1")
    assert store.get_run(rid).row_count == 1000
    assert len(store.load_payload(rid)["candidates"]) == 1000


# --- Secrets -----------------------------------------------------------------


def _db_bytes(path: Path) -> bytes:
    data = b""
    for p in (path, Path(f"{path}-wal")):
        if p.exists():
            data += p.read_bytes()
    return data


def test_stored_history_never_contains_the_api_key(tmp_path):
    clock = FakeClock()
    session = FakeSession(FakeResponse(200, csv_text(QUALIFIES, REJECTED)))
    client = FinvizClient(FAKE_KEY, session=session, sleep=clock.sleep,
                          limiter=SlidingWindowRateLimiter(clock=clock, sleep=clock.sleep))
    path = tmp_path / "memory.db"
    with ScanStore(path) as s:
        rid = s.record_scan(run_in_play_scan(client, clock=lambda: T_REGULAR), "strict_v1")
        s.record_scan_failure(FinvizNetworkError("Finviz request failed: ConnectionError"),
                              FinvizScreenConfig(), InPlayConfig(), "strict_v1", started_at=T_REGULAR)
        payload_text = str(s.load_payload(rid))
    assert FAKE_KEY not in payload_text
    assert FAKE_KEY.encode() not in _db_bytes(path)
    assert b"auth=" not in _db_bytes(path)


def test_auth_fragments_are_redacted_before_writing(store):
    leaky = row({col.NEWS_TITLE: f"see https://elite.finviz.com/x?auth={FAKE_KEY}&f=1"})
    rid = store.record_scan(make_scan(leaky), "strict_v1")
    title = store.load_payload(rid)["candidates"][0]["record"]["raw"][col.NEWS_TITLE]
    assert FAKE_KEY not in title and "auth=***&f=1" in title  # hash still verifies after redaction
    fid = store.record_scan_failure(RuntimeError(f"GET /export/screener?auth={FAKE_KEY}"),
                                    FinvizScreenConfig(), InPlayConfig(), "strict_v1", started_at=T_REGULAR)
    assert store.get_run(fid).error_message == "GET /export/screener?auth=***"
    assert FAKE_KEY.encode() not in _db_bytes(store.path)


# --- Database location -------------------------------------------------------


def test_db_path_from_environment(tmp_path):
    assert default_db_path(environ={"MEMORY_DB_PATH": str(tmp_path / "x.db")}) == tmp_path / "x.db"


def test_db_path_from_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("MEMORY_DB_PATH=runtime/other.db\n", encoding="utf-8")
    assert default_db_path(env_file=env, environ={}) == ss.PROJECT_ROOT / "runtime" / "other.db"


def test_db_path_default(tmp_path):
    assert default_db_path(env_file=tmp_path / "none.env", environ={}) == ss.PROJECT_ROOT / "runtime" / "memory.db"


def test_tests_never_touch_the_real_database():
    assert default_db_path() != ss.PROJECT_ROOT / "runtime" / "memory.db"  # conftest redirects it


def test_database_location_is_gitignored():
    rules = (ss.PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "runtime/" in rules and "*.db" in rules
