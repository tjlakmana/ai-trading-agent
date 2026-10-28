"""Phase 2: read-only dashboard API over a temporary history database (no network)."""

import gzip
import sqlite3

import pytest

from api.settings import ApiSettings
from tests.api_fixtures import (
    NOW,
    WRITE_HEADERS,
    build_history,
    make_client,
)
from tests.finviz_fixtures import FAKE_KEY, T_REGULAR


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "memory.db"
    return path, build_history(path)


@pytest.fixture
def client(db):
    return make_client(db[0])


@pytest.fixture
def ids(db):
    return db[1]


# --- Meta --------------------------------------------------------------------


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["database_exists"] is True
    assert body["order_execution_enabled"] is False and body["trading_mode"] == "RESEARCH_ONLY"
    assert body["finviz_key_configured"] is False and body["schema_version"] == 1


def test_health_without_database(tmp_path):
    body = make_client(tmp_path / "none.db").get("/api/health").json()
    assert body["database_exists"] is False
    assert not (tmp_path / "none.db").exists()  # reading never creates the database


def test_health_reports_key_presence_only(tmp_path, monkeypatch):
    from api.app import create_app
    from fastapi.testclient import TestClient
    monkeypatch.setenv("FINVIZ_API_KEY", FAKE_KEY)
    c = TestClient(create_app(ApiSettings(db_path=tmp_path / "x.db")), base_url="http://127.0.0.1:8000")
    r = c.get("/api/health")
    assert r.json()["finviz_key_configured"] is True
    assert FAKE_KEY not in r.text


def test_modules_label_unavailable_features(client):
    mods = {m["id"]: m for m in client.get("/api/modules").json()}
    assert set(mods) == {"scanner", "hod_alerts", "stock", "charts", "news", "ai_agent", "paper",
                         "level2", "history"}
    assert mods["scanner"]["status"] == "AVAILABLE" and mods["history"]["status"] == "AVAILABLE"
    assert mods["stock"]["status"] == "PARTIAL" and mods["news"]["status"] == "PARTIAL"
    for m in ("hod_alerts", "charts", "ai_agent", "paper", "level2"):
        assert mods[m]["status"] == "UNAVAILABLE" and mods[m]["detail"]
    assert "not alerts" in mods["hod_alerts"]["detail"]


def test_modules_without_any_data(tmp_path):
    mods = {m["id"]: m["status"] for m in make_client(tmp_path / "none.db").get("/api/modules").json()}
    assert mods["scanner"] == mods["history"] == mods["stock"] == "UNAVAILABLE"


def test_scanner_module_available_with_key_but_no_history(tmp_path):
    c = make_client(tmp_path / "none.db", finviz_configured=True)
    mods = {m["id"]: m["status"] for m in c.get("/api/modules").json()}
    assert mods["scanner"] == "AVAILABLE" and mods["history"] == "UNAVAILABLE"


def test_profiles(client):
    profiles = {p["name"]: p for p in client.get("/api/profiles").json()}
    assert profiles["strict_v1"]["is_default"] and not profiles["broad_v1"]["is_default"]
    assert [f["code"] for f in profiles["broad_v1"]["filters"]] == ["sh_price_2to20", "ta_change_u"]
    assert profiles["broad_v1"]["filters"][1]["meaning"] == "up on the day"


def test_in_play_config_fields(client):
    fields = {f["name"]: f for f in client.get("/api/in-play-config").json()}
    assert fields["min_pct_change"]["kind"] == "float" and fields["min_pct_change"]["unit"] == "fraction"
    assert fields["max_float_shares"]["kind"] == "int" and fields["max_float_shares"]["nullable"]
    assert fields["catalyst_level"]["kind"] == "level" and fields["catalyst_level"]["default"] == "PREFERRED"
    assert fields["min_cumulative_volume"]["default"] is None
    assert fields["min_cumulative_volume"]["scan_default"] == 500_000
    assert "negative_catalyst_types" not in fields


# --- Runs --------------------------------------------------------------------


def test_list_runs_newest_first_with_failures(client, ids):
    runs = client.get("/api/runs").json()
    assert [r["run_id"] for r in runs] == [ids["failed"], ids["strict"], ids["broad"]]
    failed = runs[0]
    assert failed["status"] == "ERROR" and failed["error"]["type"] == "FinvizAuthError"
    assert failed["freshness"]["fetched_at"] is None


def test_run_freshness_separates_fetch_time_from_quote_time(client, ids):
    run = client.get(f"/api/runs/{ids['broad']}").json()
    f = run["freshness"]
    assert f["fetched_at"].startswith("2026-10-28T18:21:00")
    assert f["fetched_at_et"] == "2026-10-28 14:21:00 EDT"
    assert f["quote_time"] is None and f["quote_freshness"] == "UNKNOWN"
    assert f["seconds_since_fetch"] == 90.0 and "no quote timestamp" in f["note"]
    assert run["counts"] == {"rows": 4, "qualified": 1, "near_miss": 1, "filtered_out": 1, "rejected": 1}
    assert run["in_play_config"]["min_cumulative_volume"] == 500_000


def test_list_runs_filters(client, ids):
    assert [r["run_id"] for r in client.get("/api/runs?profile=broad_v1").json()] == [ids["broad"]]
    assert [r["run_id"] for r in client.get("/api/runs?status=ERROR").json()] == [ids["failed"]]
    assert len(client.get("/api/runs?limit=1").json()) == 1
    assert client.get("/api/runs?status=BAD").status_code == 422
    assert client.get("/api/runs?limit=0").status_code == 422


def test_list_runs_before_needs_offset(client):
    assert client.get("/api/runs?before=2026-10-28T18:21:00").status_code == 400
    assert client.get("/api/runs?before=2026-10-28T18:21:31Z").status_code == 200


def test_runs_empty_without_database(tmp_path):
    assert make_client(tmp_path / "none.db").get("/api/runs").json() == []


def test_latest_run(client, ids):
    assert client.get("/api/runs/latest").json()["run_id"] == ids["strict"]  # failures skipped
    assert client.get("/api/runs/latest?profile=broad_v1").json()["run_id"] == ids["broad"]
    assert client.get("/api/runs/latest?profile=nope").status_code == 404


def test_latest_without_database(tmp_path):
    r = make_client(tmp_path / "none.db").get("/api/runs/latest")
    assert r.status_code == 404 and "No scans recorded yet" in r.json()["detail"]


def test_run_by_prefix_and_errors(client, ids):
    assert client.get(f"/api/runs/{ids['broad'][:8]}").json()["run_id"] == ids["broad"]
    assert client.get("/api/runs/abc").status_code == 400
    assert client.get("/api/runs/ffffffffff").status_code == 404


# --- Rows --------------------------------------------------------------------


def test_rows_default_sort_and_counts(client, ids):
    page = client.get(f"/api/runs/{ids['broad']}/rows").json()
    assert page["total"] == 4 and page["counts"]["qualified"] == 1
    assert [r["ticker"] for r in page["items"]] == ["ABCD", "EFGH", "IJKL", "MNOP"]  # % change desc, None last
    assert [r["status"] for r in page["items"]] == ["QUALIFIED", "NEAR_MISS", "FILTERED_OUT", "REJECTED"]


def test_rows_keep_origins_separate(client, ids):
    abcd = client.get(f"/api/runs/{ids['broad']}/rows?ticker=ABCD").json()["items"][0]
    assert abcd["market"]["price"] == 6.5 and abcd["market"]["average_daily_volume"] == 500_000.0
    assert abcd["market"]["float_shares"] == 6_000_000 and abcd["market"]["day_high"] == 6.8
    assert abcd["calculated"]["pct_change"] == pytest.approx(0.30)
    assert abcd["calculated"]["gap_pct"] == pytest.approx(0.20)
    assert abcd["calculated"]["volume_vs_avg_daily"] == pytest.approx(8.0)
    assert abcd["calculated"]["pct_below_day_high"] == pytest.approx((6.8 - 6.5) / 6.8)
    assert abcd["vendor"]["relative_volume"] == 9.5  # Finviz's, kept apart from our 8.0
    assert abcd["vendor"]["change_pct"] == pytest.approx(0.30)
    assert abcd["news"] == {"time": "2026-10-28 08:00:00", "title": "Abcd announces FDA approval",
                            "classification": "UNCLASSIFIED"}
    assert abcd["company"] == "Abcd Therapeutics Inc" and abcd["exchange"] == "NASD"


def test_rows_filter_by_status(client, ids):
    page = client.get(f"/api/runs/{ids['broad']}/rows?status=NEAR_MISS&status=REJECTED").json()
    assert [r["ticker"] for r in page["items"]] == ["EFGH", "MNOP"] and page["total"] == 2
    near = page["items"][0]
    assert near["failed_hard_checks"] == ["min_pct_change"] and near["hard_failures"] == 1
    assert near["reasons"] and "% change" in near["reasons"][0]
    rejected = page["items"][1]
    assert rejected["reasons"] == ["Prev Close is missing"] and rejected["hard_failures"] is None


def test_rows_top_gappers_sort(client, ids):
    items = client.get(f"/api/runs/{ids['broad']}/rows?sort=gap_pct").json()["items"]
    gaps = [r["calculated"]["gap_pct"] for r in items]
    assert gaps[0] == pytest.approx(0.20) and gaps[1] == pytest.approx(0.02)
    assert gaps[2:] == [None, None]  # IJKL has no open; MNOP rejected


def test_rows_sort_ascending_and_by_ticker(client, ids):
    items = client.get(f"/api/runs/{ids['broad']}/rows?sort=ticker&order=asc").json()["items"]
    assert [r["ticker"] for r in items] == ["ABCD", "EFGH", "IJKL", "MNOP"]
    items = client.get(f"/api/runs/{ids['broad']}/rows?sort=float_shares&order=asc").json()["items"]
    assert [r["ticker"] for r in items][:3] == ["ABCD", "EFGH", "IJKL"]


def test_rows_pagination(client, ids):
    page = client.get(f"/api/runs/{ids['broad']}/rows?limit=2&offset=1").json()
    assert page["total"] == 4 and [r["ticker"] for r in page["items"]] == ["EFGH", "IJKL"]


@pytest.mark.parametrize("query", ["sort=secret", "status=BAD", "limit=501", "offset=-1", "ticker=A%26B",
                                   "order=sideways"])
def test_rows_bad_queries(client, ids, query):
    assert client.get(f"/api/runs/{ids['broad']}/rows?{query}").status_code in (400, 422)


def test_rows_of_failed_run(client, ids):
    r = client.get(f"/api/runs/{ids['failed']}/rows")
    assert r.status_code == 409 and "no payload" in r.json()["detail"]


# --- Row detail --------------------------------------------------------------


def test_row_detail_explains_every_check(client, ids):
    d = client.get(f"/api/runs/{ids['broad']}/rows/2").json()
    assert d["ticker"] == "EFGH" and d["status"] == "NEAR_MISS" and d["qualified"] is False
    hard = {c["name"]: c for c in d["hard_checks"]}
    assert hard["min_pct_change"]["status"] == "FAIL"
    assert hard["min_pct_change"]["threshold"] == 0.10 and hard["min_pct_change"]["message"]
    assert hard["min_cumulative_volume"]["status"] == "PASS"
    assert hard["min_cumulative_volume"]["actual"] == 4_000_000
    assert isinstance(hard["min_cumulative_volume"]["actual"], int)  # share counts stay whole numbers
    assert isinstance(hard["max_float_shares"]["threshold"], int)
    assert {c["level"] for c in d["quality_checks"]} == {"PREFERRED"}
    assert d["raw"]["Price"] == "5.20" and d["session"] == "REGULAR"
    assert d["freshness"]["quote_freshness"] == "UNKNOWN" and d["freshness"]["quote_time"] is None


def test_rejected_row_detail(client, ids):
    d = client.get(f"/api/runs/{ids['broad']}/rows/4").json()
    assert d["status"] == "REJECTED" and d["normalization_errors"] == ["Prev Close is missing"]
    assert d["hard_checks"] == [] and d["qualified"] is None
    assert d["raw"]["Prev Close"] == "-"


def test_row_detail_errors(client, ids):
    assert client.get(f"/api/runs/{ids['broad']}/rows/99").status_code == 404
    assert client.get(f"/api/runs/{ids['failed']}/rows/1").status_code == 409


def test_integrity_failure_is_reported(db):
    path, ids = db
    conn = sqlite3.connect(path)
    conn.execute("DROP TRIGGER scan_payloads_no_update")
    conn.execute("UPDATE scan_payloads SET payload = ? WHERE run_id = ?", (gzip.compress(b"{}"), ids["broad"]))
    conn.commit()
    conn.close()
    r = make_client(path).get(f"/api/runs/{ids['broad']}/rows")
    assert r.status_code == 500 and "SHA-256" in r.json()["detail"]


# --- Ticker history ----------------------------------------------------------


def test_ticker_history(client, ids):
    body = client.get("/api/tickers/abcd/history").json()
    assert body["ticker"] == "ABCD"
    assert [(o["run_id"], o["profile"], o["status"]) for o in body["observations"]] == [
        (ids["strict"], "strict_v1", "QUALIFIED"), (ids["broad"], "broad_v1", "QUALIFIED")]
    assert body["observations"][0]["pct_change"] == pytest.approx(0.30)


def test_ticker_history_unknown_and_invalid(client, tmp_path):
    assert client.get("/api/tickers/ZZZZ/history").json()["observations"] == []
    assert client.get("/api/tickers/A%26B/history").status_code == 422
    assert make_client(tmp_path / "none.db").get("/api/tickers/ABCD/history").json()["observations"] == []


# --- Local-only security -----------------------------------------------------


def test_non_loopback_host_header_rejected(client):
    for host in ("evil.example.com", "192.168.1.5:8000", "127.0.0.1.evil.com"):
        r = client.get("/api/health", headers={"Host": host})
        assert r.status_code == 403, host


def test_loopback_host_names_accepted(client):
    for host in ("127.0.0.1:8000", "localhost:8000", "[::1]:8000", "localhost"):
        assert client.get("/api/health", headers={"Host": host}).status_code == 200, host


def test_state_changing_requests_need_dashboard_header(client, ids):
    url = f"/api/runs/{ids['broad']}/replay"
    assert client.post(url, json={}).status_code == 403
    assert client.post(url, json={}, headers={**WRITE_HEADERS, "Origin": "https://evil.example"}).status_code == 403
    assert client.post(url, json={}, headers=WRITE_HEADERS).status_code == 200


def test_responses_are_not_cached(client):
    r = client.get("/api/health")
    assert r.headers["cache-control"] == "no-store" and r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com"])
def test_settings_refuse_non_loopback_binding(host):
    with pytest.raises(ValueError, match="loopback"):
        ApiSettings(host=host)


def test_no_endpoint_can_trade(client):
    paths = set(client.get("/openapi.json").json()["paths"])
    assert "/api/health" in paths and "/api/runs/{run_id}/rows" in paths
    assert not any(word in p for p in paths for word in ("order", "trade", "execute", "risk", "position"))


def test_responses_never_contain_secrets(client, ids, monkeypatch):
    monkeypatch.setenv("FINVIZ_API_KEY", FAKE_KEY)
    for url in ("/api/health", "/api/modules", "/api/runs", f"/api/runs/{ids['broad']}/rows",
                f"/api/runs/{ids['broad']}/rows/1", "/api/tickers/ABCD/history", "/openapi.json"):
        text = client.get(url).text
        assert FAKE_KEY not in text and "auth=" not in text, url


def test_reads_use_fixed_clock(client):
    assert client.get("/api/health").json()["server_time"].startswith(NOW.isoformat()[:19])
    assert T_REGULAR < NOW
