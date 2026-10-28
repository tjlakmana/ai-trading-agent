"""Phase 1 dashboard support: store read methods, payload cache, shared recording helper."""

import gzip
import sqlite3
import threading
from datetime import timedelta

import pytest

from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizAuthError, FinvizCredentialsError
from data.finviz.profiles import DEFAULT_MIN_VOLUME, default_scan_in_play_config
from memory.recording import run_and_record
from memory.scan_store import HistoryIntegrityError, PayloadCache, ScanStore
from strategy.in_play_config import InPlayConfig
from tests.finviz_fixtures import T_REGULAR, FakeClient, csv_text, row
from tests.test_scan_store import FILTERED, NEAR_MISS, QUALIFIES, REJECTED, make_scan

MINUTE = timedelta(minutes=1)


@pytest.fixture
def store(tmp_path):
    with ScanStore(tmp_path / "memory.db") as s:
        yield s


def record(store, profile="strict_v1", minutes=0, rows=(QUALIFIES,)):
    at = T_REGULAR + minutes * MINUTE
    return store.record_scan(make_scan(*rows, at=at), profile, started_at=at)


def fail(store, profile="strict_v1", minutes=0):
    return store.record_scan_failure(FinvizAuthError("Finviz rejected the API key (HTTP 401)"),
                                     FinvizScreenConfig(), InPlayConfig(), profile,
                                     started_at=T_REGULAR + minutes * MINUTE)


# --- list_runs filters / latest_run ------------------------------------------


def test_list_runs_filters(store):
    a = record(store, "broad_v1", 0)
    b = record(store, "strict_v1", 1)
    c = fail(store, "strict_v1", 2)
    assert [r.run_id for r in store.list_runs()] == [c, b, a]
    assert [r.run_id for r in store.list_runs(profile="strict_v1")] == [c, b]
    assert [r.run_id for r in store.list_runs(status="OK")] == [b, a]
    assert [r.run_id for r in store.list_runs(status="ERROR")] == [c]
    assert [r.run_id for r in store.list_runs(before=T_REGULAR + 2 * MINUTE)] == [b, a]
    assert store.list_runs(profile="nope") == ()


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 1001}, {"limit": True}, {"status": "BAD"}])
def test_list_runs_rejects_bad_arguments(store, kwargs):
    with pytest.raises(ValueError):
        store.list_runs(**kwargs)


def test_latest_run_skips_failures(store):
    assert store.latest_run() is None
    ok = record(store, "broad_v1", 0)
    fail(store, "broad_v1", 1)
    assert store.latest_run().run_id == ok
    assert store.latest_run("broad_v1").run_id == ok
    assert store.latest_run("strict_v1") is None


# --- get_entry ---------------------------------------------------------------


def test_get_entry_candidate_and_rejected(store):
    rid = record(store, rows=(QUALIFIES, NEAR_MISS, FILTERED, REJECTED))
    c = store.get_entry(rid, 2)
    assert c["kind"] == "candidate" and c["record"]["ticker"] == "EFGH"
    assert c["classification"] == "NEAR_MISS"
    assert c["result"]["hard_checks"]
    r = store.get_entry(rid, 4)
    assert r["kind"] == "rejected" and r["record"]["errors"] == ["Prev Close is missing"]
    with pytest.raises(KeyError):
        store.get_entry(rid, 99)


def test_get_entry_of_failed_run(store):
    with pytest.raises(ValueError, match="no payload"):
        store.get_entry(fail(store), 1)


# --- PayloadCache ------------------------------------------------------------


def test_cache_is_used_and_shared_across_stores(tmp_path):
    cache = PayloadCache(max_runs=2)
    path = tmp_path / "memory.db"
    with ScanStore(path, payload_cache=cache) as s:
        rid = record(s)
        first = s.load_payload(rid)
    with ScanStore(path, read_only=True, payload_cache=cache) as s:
        assert s.load_payload(rid) is first  # served from the shared cache
    assert len(cache) == 1


def test_cache_evicts_least_recently_used():
    cache = PayloadCache(max_runs=2)
    cache.put(("a", "1"), {"a": 1})
    cache.put(("b", "2"), {"b": 2})
    assert cache.get(("a", "1")) == {"a": 1}  # a is now most recent
    cache.put(("c", "3"), {"c": 3})
    assert cache.get(("b", "2")) is None
    assert cache.get(("a", "1")) and cache.get(("c", "3"))


def test_cache_only_holds_verified_payloads(tmp_path):
    cache = PayloadCache()
    path = tmp_path / "memory.db"
    with ScanStore(path, payload_cache=cache) as s:
        rid = record(s)
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER scan_payloads_no_update")
    conn.execute("UPDATE scan_payloads SET payload = ?", (gzip.compress(b"{}"),))
    conn.commit()
    conn.close()
    with ScanStore(path, payload_cache=cache) as s:
        with pytest.raises(HistoryIntegrityError):
            s.load_payload(rid)
    assert len(cache) == 0


def test_cache_is_thread_safe():
    cache = PayloadCache(max_runs=8)
    errors = []

    def worker(n):
        try:
            for i in range(500):
                cache.put((f"{n}-{i % 10}", "h"), {"i": i})
                cache.get((f"{n}-{(i + 3) % 10}", "h"))
        except Exception as exc:  # pragma: no cover - only on failure
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == [] and len(cache) <= 8


@pytest.mark.parametrize("bad", [0, -1, 1.5])
def test_cache_size_must_be_positive(bad):
    with pytest.raises(ValueError):
        PayloadCache(bad)


def test_replay_with_cache_matches_without(tmp_path):
    path = tmp_path / "memory.db"
    with ScanStore(path) as s:
        rid = record(s, rows=(QUALIFIES, NEAR_MISS, FILTERED))
        plain = [i.classification for i in s.replay(rid)]
    with ScanStore(path, payload_cache=PayloadCache()) as s:
        assert [i.classification for i in s.replay(rid)] == plain
        assert [i.classification for i in s.replay(rid)] == plain  # second call from cache


# --- run_and_record ----------------------------------------------------------


def test_run_and_record_success(store):
    out = run_and_record(lambda: FakeClient(csv_text(QUALIFIES, NEAR_MISS)), FinvizScreenConfig(),
                         default_scan_in_play_config(), "strict_v1", store=store, clock=lambda: T_REGULAR)
    assert out.ok and out.error is None and out.started_at == T_REGULAR
    assert len(out.scan.candidates) == 2
    assert store.get_run(out.run_id).qualified_count == 1


def test_run_and_record_failure_is_recorded_not_raised(store):
    out = run_and_record(lambda: FakeClient(error=FinvizAuthError("HTTP 401")), FinvizScreenConfig(),
                         InPlayConfig(), "strict_v1", store=store, clock=lambda: T_REGULAR)
    assert not out.ok and out.scan is None and isinstance(out.error, FinvizAuthError)
    assert store.get_run(out.run_id).status == "ERROR"


def test_client_factory_errors_are_recorded(store):
    def no_key():
        raise FinvizCredentialsError("FINVIZ_API_KEY is not set (environment or .env)")
    out = run_and_record(no_key, FinvizScreenConfig(), InPlayConfig(), "strict_v1",
                         store=store, clock=lambda: T_REGULAR)
    assert store.get_run(out.run_id).error_type == "FinvizCredentialsError"


def test_run_and_record_without_store():
    out = run_and_record(lambda: FakeClient(csv_text(QUALIFIES)), FinvizScreenConfig(), InPlayConfig(),
                         "strict_v1", clock=lambda: T_REGULAR)
    assert out.ok and out.run_id is None


def test_storage_errors_propagate(tmp_path):
    s = ScanStore(tmp_path / "memory.db")
    s.close()
    with pytest.raises(sqlite3.ProgrammingError):
        run_and_record(lambda: FakeClient(csv_text(QUALIFIES)), FinvizScreenConfig(), InPlayConfig(),
                       "strict_v1", store=s, clock=lambda: T_REGULAR)


def test_default_scan_config():
    assert default_scan_in_play_config() == InPlayConfig(min_cumulative_volume=DEFAULT_MIN_VOLUME)
    assert DEFAULT_MIN_VOLUME == 500_000
