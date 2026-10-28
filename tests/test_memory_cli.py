"""Tests for scan recording in the Finviz CLI and for python -m memory. All mocked."""

from datetime import timedelta

import pytest

from data.finviz import cli as finviz_cli
from data.finviz import schema as col
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizAuthError
from data.finviz.profiles import BROAD_V1, DEFAULT_PROFILE, PROFILES, STRICT_V1
from memory import cli as memory_cli
from memory.scan_store import ScanStore, default_db_path
from tests.finviz_fixtures import FAKE_KEY, T_REGULAR, FakeClient, csv_text, row

QUALIFIES = row()
NEAR_MISS = row({col.TICKER: "EFGH", col.PRICE: "5.20"})
FILTERED = row({col.TICKER: "IJKL", col.PRICE: "5.20", col.SHARES_FLOAT: "50.00"})


def scan_cli(capsys, argv, client):
    code = finviz_cli.main(argv, client=client, clock=lambda: T_REGULAR)
    return (code, *capsys.readouterr())


def memory(capsys, argv):
    code = memory_cli.main(argv)
    return (code, *capsys.readouterr())


# --- Profiles ----------------------------------------------------------------


def test_profiles():
    assert PROFILES[BROAD_V1] == FinvizScreenConfig(filters=("sh_price_2to20", "ta_change_u"))
    assert PROFILES[STRICT_V1] == FinvizScreenConfig()
    assert DEFAULT_PROFILE == STRICT_V1
    with pytest.raises(TypeError):
        PROFILES["mine"] = FinvizScreenConfig()  # read-only


# --- Recording from python -m data.finviz ------------------------------------


def test_scan_is_recorded_by_default(capsys):
    code, out, _ = scan_cli(capsys, [], FakeClient(csv_text(QUALIFIES, NEAR_MISS)))
    assert code == 0 and "recorded as run" in out
    with ScanStore(default_db_path(), read_only=True) as s:
        (run,) = s.list_runs()
        assert run.profile_name == STRICT_V1 and run.status == "OK"
        assert (run.qualified_count, run.near_miss_count) == (1, 1)


def test_no_record_writes_nothing(capsys):
    code, out, _ = scan_cli(capsys, ["--no-record"], FakeClient(csv_text(QUALIFIES)))
    assert code == 0 and "recorded" not in out
    assert not default_db_path().exists()


def test_broad_profile_is_requested_and_recorded(capsys):
    client = FakeClient(csv_text(QUALIFIES, NEAR_MISS, FILTERED))
    _, out, _ = scan_cli(capsys, ["--profile", "broad_v1"], client)
    assert client.configs == [PROFILES[BROAD_V1]]
    assert "profile         broad_v1: sh_price_2to20, ta_change_u" in out
    assert "qualified 1 | near-miss 1 | filtered out 1" in out
    with ScanStore(default_db_path(), read_only=True) as s:
        assert s.list_runs()[0].profile_name == BROAD_V1


def test_tickers_are_recorded_as_custom_profile(capsys):
    scan_cli(capsys, ["--tickers", "ABCD"], FakeClient(csv_text(QUALIFIES)))
    with ScanStore(default_db_path(), read_only=True) as s:
        assert s.list_runs()[0].profile_name == "custom_tickers"


def test_failed_attempt_is_recorded(capsys):
    error = FinvizAuthError("Finviz rejected the API key (HTTP 401)")
    code, out, err = scan_cli(capsys, [], FakeClient(error=error))
    assert code == 1 and out == ""
    assert "HTTP 401" in err and "failed attempt recorded" in err
    with ScanStore(default_db_path(), read_only=True) as s:
        (run,) = s.list_runs()
        assert (run.status, run.error_type) == ("ERROR", "FinvizAuthError")


def test_missing_credentials_attempt_is_recorded(capsys):
    code = finviz_cli.main([], clock=lambda: T_REGULAR)
    _, err = capsys.readouterr()
    assert code == 2 and "FINVIZ_API_KEY is not set" in err
    with ScanStore(default_db_path(), read_only=True) as s:
        assert s.list_runs()[0].error_type == "FinvizCredentialsError"


def test_show_near_miss_lists_only_near_misses(capsys):
    _, out, _ = scan_cli(capsys, ["--show-near-miss", "--no-record"],
                         FakeClient(csv_text(QUALIFIES, NEAR_MISS, FILTERED)))
    assert "NEAR MISS" in out and "EFGH" in out and "IJKL" not in out


def test_show_all_labels_each_class(capsys):
    _, out, _ = scan_cli(capsys, ["--show-all", "--no-record"],
                         FakeClient(csv_text(QUALIFIES, NEAR_MISS, FILTERED)))
    assert "EFGH   NEAR_MISS" in out and "IJKL   FILTERED_OUT" in out


def test_injected_store_is_used(capsys, tmp_path):
    with ScanStore(tmp_path / "other.db") as s:
        finviz_cli.main([], client=FakeClient(csv_text(QUALIFIES)), clock=lambda: T_REGULAR, store=s)
        assert len(s.list_runs()) == 1
    assert not default_db_path().exists()


# --- python -m memory --------------------------------------------------------


@pytest.fixture
def history(capsys):
    """Two successful runs and one failure in the default (temporary) database."""
    scan_cli(capsys, ["--profile", "broad_v1"], FakeClient(csv_text(QUALIFIES, NEAR_MISS, FILTERED)))
    finviz_cli.main([], client=FakeClient(csv_text(row({col.PRICE: "5.20"}))),
                    clock=lambda: T_REGULAR + timedelta(minutes=5))
    finviz_cli.main([], client=FakeClient(error=FinvizAuthError("Finviz rejected the API key (HTTP 401)")),
                    clock=lambda: T_REGULAR + timedelta(minutes=10))
    capsys.readouterr()
    with ScanStore(default_db_path(), read_only=True) as s:
        return [r.run_id for r in s.list_runs()]  # newest first: [error, strict, broad]


def test_memory_without_database(capsys):
    code, _, err = memory(capsys, ["runs"])
    assert code == 2 and "Run a scan first" in err


def test_memory_runs(capsys, history):
    code, out, _ = memory(capsys, ["runs"])
    assert code == 0
    lines = out.splitlines()
    assert "ERROR" in lines[1] and "FinvizAuthError: Finviz rejected the API key (HTTP 401)" in lines[1]
    assert "strict_v1" in lines[2] and "broad_v1" in lines[3]


def test_memory_show(capsys, history):
    code, out, _ = memory(capsys, ["show", history[2][:8]])
    assert code == 0
    assert "quote freshness UNKNOWN" in out and "fetched_at      2026-10-28T18:21:00+00:00" in out
    assert "qualified 1 | near-miss 1 | filtered out 1" in out
    assert out.index("ABCD") < out.index("EFGH") < out.index("IJKL")  # grouped by class


def test_memory_show_filters_by_status(capsys, history):
    _, out, _ = memory(capsys, ["show", history[2][:8], "--status", "NEAR_MISS"])
    assert "EFGH" in out and "IJKL" not in out


def test_memory_show_failed_run(capsys, history):
    _, out, _ = memory(capsys, ["show", history[0][:8]])
    assert "status ERROR" in out and "no data received" in out and "FinvizAuthError" in out


def test_memory_ticker(capsys, history):
    code, out, _ = memory(capsys, ["ticker", "ABCD"])
    assert code == 0 and "2 observation(s)" in out
    assert out.index("NEAR_MISS") < out.index("QUALIFIED")  # newest first


def test_memory_replay(capsys, history):
    code, out, _ = memory(capsys, ["replay", history[2][:8], "--set", "min_pct_change=0.02"])
    assert code == 0
    assert "qualified 2 | near-miss 1 | filtered out 0 | changed class 2" in out
    assert "EFGH       NEAR_MISS -> QUALIFIED" in out


def test_memory_replay_original_config(capsys, history):
    _, out, _ = memory(capsys, ["replay", history[2][:8]])
    assert "original config" in out and "changed class 0" in out


@pytest.mark.parametrize("setting", ["nonsense=1", "negative_catalyst_types=x", "min_price=-1",
                                     "min_pct_change", "catalyst_level=SOMETIMES"])
def test_memory_replay_bad_settings(capsys, history, setting):
    code, _, err = memory(capsys, ["replay", history[2][:8], "--set", setting])
    assert code == 2 and err.startswith("error:")


def test_memory_replay_typed_settings(capsys, history):
    code, out, _ = memory(capsys, ["replay", history[2][:8], "--set", "max_float_shares=none",
                                   "--set", "catalyst_level=hard", "--set", "min_cumulative_volume=1_000"])
    assert code == 0 and "'max_float_shares': None" in out and "Level.HARD" in out


def test_memory_unknown_run(capsys, history):
    code, _, err = memory(capsys, ["show", "ffffffff"])
    assert code == 2 and "no unique scan run" in err


def test_memory_output_contains_no_secret(capsys, history):
    for argv in (["runs"], ["show", history[2][:8]], ["ticker", "ABCD"]):
        _, out, err = memory(capsys, argv)
        assert FAKE_KEY not in out + err and "auth=" not in out + err
