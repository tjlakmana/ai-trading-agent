"""Phase 4: guarded manual Finviz scans ("Run scan now"). Mocked Finviz client only."""

import threading

import pytest

from data.finviz.errors import FinvizAuthError
from memory.scan_store import ScanStore
from tests.api_fixtures import NEAR_MISS, QUALIFIES, REJECTED, WRITE_HEADERS, make_client
from tests.finviz_fixtures import FAKE_KEY, FakeClient, connection_error_with_key, csv_text


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def inline(fn):
    fn()


def start(client, profile="broad_v1"):
    return client.post("/api/scans", json={"profile": profile}, headers=WRITE_HEADERS)


@pytest.fixture
def db(tmp_path):
    return tmp_path / "memory.db"


def scan_client(db, client=None, *, launcher=inline, monotonic=None, **kwargs):
    fake = client or FakeClient(csv_text(QUALIFIES, NEAR_MISS, REJECTED))
    return make_client(db, client_factory=lambda: fake, scan_launcher=launcher,
                       monotonic=monotonic or Clock(), **kwargs), fake


# --- Success -----------------------------------------------------------------


def test_scan_runs_and_is_recorded(db):
    client, fake = scan_client(db)
    r = start(client)
    assert r.status_code == 202
    job = r.json()
    assert job["state"] == "SUCCEEDED" and job["profile"] == "broad_v1"
    assert job["counts"] == {"rows": 3, "qualified": 1, "near_miss": 1, "filtered_out": 0, "rejected": 1}
    assert fake.configs[0].filters == ("sh_price_2to20", "ta_change_u")
    with ScanStore(db, read_only=True) as s:
        run = s.get_run(job["run_id"])
        assert run.profile_name == "broad_v1" and run.in_play_config["min_cumulative_volume"] == 500_000
    # The new run is immediately visible to the read API.
    assert client.get("/api/runs/latest").json()["run_id"] == job["run_id"]
    assert client.get(f"/api/scans/{job['job_id']}").json() == job


def test_strict_profile(db):
    client, fake = scan_client(db)
    assert start(client, "strict_v1").json()["state"] == "SUCCEEDED"
    assert len(fake.configs[0].filters) == 5


# --- Validation and request guards -------------------------------------------


@pytest.mark.parametrize("profile", ["custom", "", "broad_v1; DROP TABLE"])
def test_unknown_profile_rejected(db, profile):
    client, fake = scan_client(db)
    r = start(client, profile)
    assert r.status_code == 400 and "unknown profile" in r.json()["detail"]
    assert fake.configs == [] and not db.exists()


def test_tickers_or_filters_cannot_be_injected(db):
    client, fake = scan_client(db)
    r = client.post("/api/scans", json={"profile": "broad_v1", "filters": ["zz_bogus"], "tickers": ["X"]},
                    headers=WRITE_HEADERS)
    assert r.status_code == 202
    assert fake.configs[0].filters == ("sh_price_2to20", "ta_change_u") and fake.configs[0].tickers == ()


def test_scan_requires_dashboard_header(db):
    client, fake = scan_client(db)
    assert client.post("/api/scans", json={"profile": "broad_v1"}).status_code == 403
    assert client.post("/api/scans", json={"profile": "broad_v1"},
                       headers={**WRITE_HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert fake.configs == []


def test_unknown_job(db):
    client, _ = scan_client(db)
    assert client.get("/api/scans/nope").status_code == 404


# --- Failures are recorded and reported --------------------------------------


def test_finviz_failure_is_recorded(db):
    client, _ = scan_client(db, FakeClient(error=FinvizAuthError("Finviz rejected the API key (HTTP 401)")))
    job = start(client).json()
    assert job["state"] == "FAILED" and job["counts"] is None
    assert job["error"] == {"type": "FinvizAuthError", "message": "Finviz rejected the API key (HTTP 401)"}
    run = client.get(f"/api/runs/{job['run_id']}").json()
    assert run["status"] == "ERROR" and run["error"]["type"] == "FinvizAuthError"


def test_missing_credentials_is_a_recorded_failure(db):
    # Real factory: conftest guarantees no key, so this fails before any request.
    client = make_client(db, scan_launcher=inline, monotonic=Clock())
    job = start(client).json()
    assert job["state"] == "FAILED" and job["error"]["type"] == "FinvizCredentialsError"
    assert client.get("/api/scans/status").json()["finviz_key_configured"] is False


def test_unexpected_error_is_reported_and_recorded_without_secrets(db):
    class Broken:
        def fetch_screener_csv(self, config):
            raise RuntimeError(f"boom at /export/screener?auth={FAKE_KEY}")

    client, _ = scan_client(db, Broken())
    r = start(client)
    job = r.json()
    assert job["state"] == "FAILED" and job["error"]["type"] == "RuntimeError"
    assert FAKE_KEY not in r.text and "auth=***" in job["error"]["message"]
    run = client.get(f"/api/runs/{job['run_id']}").json()
    assert run["status"] == "ERROR" and FAKE_KEY not in run["error"]["message"]


def test_network_error_message_is_key_safe(db):
    from data.finviz.client import FinvizClient, SlidingWindowRateLimiter
    from tests.finviz_fixtures import FakeClock, FakeSession
    clock = FakeClock()
    finviz = FinvizClient(FAKE_KEY, session=FakeSession(connection_error_with_key()), sleep=clock.sleep,
                          limiter=SlidingWindowRateLimiter(clock=clock, sleep=clock.sleep))
    client, _ = scan_client(db, finviz)
    r = start(client)
    assert r.json()["error"]["type"] == "FinvizNetworkError" and FAKE_KEY not in r.text


# --- Duplicate protection and cooldown ---------------------------------------


class BlockingClient:
    def __init__(self, text):
        self.text, self.release, self.entered = text, threading.Event(), threading.Event()

    def fetch_screener_csv(self, config):
        self.entered.set()
        assert self.release.wait(5), "test did not release the scan"
        return self.text


def test_duplicate_request_while_running_returns_the_running_job(db):
    threads = []

    def launcher(fn):
        t = threading.Thread(target=fn)
        threads.append(t)
        t.start()

    blocking = BlockingClient(csv_text(QUALIFIES))
    client, _ = scan_client(db, blocking, launcher=launcher)
    first = start(client).json()
    assert first["state"] == "RUNNING" and first["finished_at"] is None
    assert blocking.entered.wait(5)
    status = client.get("/api/scans/status").json()
    assert status["running"]["job_id"] == first["job_id"]

    dup = start(client, "strict_v1")
    assert dup.status_code == 409 and dup.json()["job"]["job_id"] == first["job_id"]

    blocking.release.set()
    threads[0].join(5)
    done = client.get(f"/api/scans/{first['job_id']}").json()
    assert done["state"] == "SUCCEEDED" and done["finished_at"] is not None
    assert client.get("/api/scans/status").json()["running"] is None
    with ScanStore(db, read_only=True) as s:
        assert len(s.list_runs()) == 1  # the duplicate never ran


def test_cooldown_after_a_scan(db):
    mono = Clock()
    client, fake = scan_client(db, monotonic=mono)
    assert start(client).status_code == 202
    mono.now += 10
    r = start(client)
    assert r.status_code == 429 and r.headers["retry-after"] == "20"
    assert r.json()["retry_after_seconds"] == 20
    assert client.get("/api/scans/status").json()["cooldown_remaining_seconds"] == 20.0
    mono.now += 20
    assert start(client).status_code == 202
    assert len(fake.configs) == 2


def test_cooldown_also_follows_failures(db):
    mono = Clock()
    client, _ = scan_client(db, FakeClient(error=FinvizAuthError("HTTP 401")), monotonic=mono)
    start(client)
    assert start(client).status_code == 429


def test_status_before_any_scan(db):
    client, _ = scan_client(db)
    body = client.get("/api/scans/status").json()
    assert body["running"] is None and body["latest"] is None
    assert body["cooldown_seconds"] == 30.0 and body["cooldown_remaining_seconds"] == 0.0


def test_launch_failure_releases_the_lock(db):
    def broken_launcher(fn):
        raise RuntimeError("no threads")

    client, _ = scan_client(db, launcher=broken_launcher)
    with pytest.raises(RuntimeError):
        start(client)
    assert client.get("/api/scans/status").json()["running"] is None
