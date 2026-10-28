"""Integration tests: Finviz discovery -> in-play filter, and the manual CLI. All mocked."""

from datetime import timedelta

import pytest

from data.finviz import cli
from data.finviz import schema as col
from data.finviz.client import FinvizClient, SlidingWindowRateLimiter
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizAuthError, FinvizResponseError
from data.finviz.parse import QuoteFreshness
from data.finviz.scan import run_in_play_scan
from data.market_hours import Session
from strategy.in_play import CheckStatus
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

QUALIFIES = row()  # ABCD: +30%, 8x avg volume, 6M float
SMALL_MOVE = row({col.TICKER: "EFGH", col.PRICE: "5.20"})  # +4% < +10%
NO_PRICE = row({col.TICKER: "IJKL", col.PRICE: "-"})  # cannot be normalized
NO_FLOAT = row({col.TICKER: "MNOP", col.SHARES_FLOAT: "-"})  # HARD float unknown


def scan(*rows, in_play=None, screen=None, at=T_REGULAR):
    client = FakeClient(csv_text(*rows))
    return run_in_play_scan(client, screen, in_play, clock=lambda: at), client


# --- Integration with evaluate_universe --------------------------------------


def test_every_row_is_accounted_for():
    result, _ = scan(QUALIFIES, SMALL_MOVE, NO_PRICE, NO_FLOAT)
    assert [c.record.ticker for c in result.candidates] == ["ABCD", "EFGH", "MNOP"]
    assert [r.ticker for r in result.rejected] == ["IJKL"]
    assert [c.record.ticker for c in result.qualified] == ["ABCD"]
    assert [c.record.ticker for c in result.not_qualified] == ["EFGH", "MNOP"]


def test_result_evaluates_the_records_own_snapshot():
    result, _ = scan(QUALIFIES, SMALL_MOVE)
    for c in result.candidates:
        assert c.result.snapshot is c.record.snapshot
        assert c.result.config is result.in_play_config


def test_failures_keep_explanations():
    result, _ = scan(SMALL_MOVE, NO_PRICE, NO_FLOAT)
    by_ticker = {c.record.ticker: c.result for c in result.candidates}
    assert any("% change" in r for r in by_ticker["EFGH"].reasons)
    assert any("float unknown" in r for r in by_ticker["MNOP"].reasons)
    assert result.rejected[0].errors == ("Price is missing",)


def test_in_play_metrics_are_ours_not_finvizs():
    # Finviz claims -50% and RVOL 0.01; our calculation from raw prices/volume still qualifies.
    result, _ = scan(row({col.CHANGE: "-50.00%", col.RELATIVE_VOLUME: "0.01"}))
    (c,) = result.candidates
    assert c.result.qualified
    assert c.result.metrics.pct_change == pytest.approx(0.30)
    assert c.result.metrics.volume_vs_avg_daily == pytest.approx(8.0)
    assert c.record.vendor.change_pct == pytest.approx(-0.50)


def test_vendor_says_up_but_raw_data_says_down_is_not_qualified():
    result, _ = scan(row({col.PRICE: "4.00", col.CHANGE: "30.00%"}))
    assert not result.candidates[0].result.qualified


def test_scan_metadata():
    result, client = scan(QUALIFIES)
    assert result.fetched_at == T_REGULAR
    assert result.session is Session.REGULAR
    assert result.quote_freshness is QuoteFreshness.UNKNOWN
    assert result.screen_config == FinvizScreenConfig()
    assert result.in_play_config == InPlayConfig()
    assert client.configs == [FinvizScreenConfig()]


def test_custom_configs_are_used():
    screen = FinvizScreenConfig(filters=(), tickers=("ABCD",))
    in_play = InPlayConfig(min_pct_change=0.50)
    result, client = scan(QUALIFIES, screen=screen, in_play=in_play)
    assert client.configs == [screen]
    assert not result.candidates[0].result.qualified  # +30% < +50%


def test_staleness_is_about_fetch_age():
    result, _ = scan(QUALIFIES)
    assert result.age_seconds(T_REGULAR + timedelta(seconds=45)) == 45
    assert not result.is_stale(T_REGULAR + timedelta(seconds=30), max_age_seconds=30)
    assert result.is_stale(T_REGULAR + timedelta(seconds=31), max_age_seconds=30)


def test_empty_screen_result():
    result, _ = scan()
    assert result.candidates == () and result.rejected == () and result.qualified == ()


def test_bad_configs_rejected():
    with pytest.raises(TypeError):
        run_in_play_scan(FakeClient(""), {"f": "x"})
    with pytest.raises(TypeError):
        run_in_play_scan(FakeClient(""), None, {"min_price": 1})


def test_client_errors_propagate():
    with pytest.raises(FinvizAuthError):
        run_in_play_scan(FakeClient(error=FinvizAuthError("rejected")))


def test_unexpected_header_propagates():
    with pytest.raises(FinvizResponseError):
        run_in_play_scan(FakeClient("Ticker,Price\nABCD,6.5\n"), clock=lambda: T_REGULAR)


# --- min_cumulative_volume through the whole pipeline ------------------------


def test_min_volume_disabled_by_default():
    result, _ = scan(row({col.VOLUME: "1600000", col.AVERAGE_VOLUME: "500"}))
    names = {ch.name for ch in result.candidates[0].result.hard_checks}
    assert "min_cumulative_volume" not in names


@pytest.mark.parametrize("volume, ok", [("2000000", True), ("1999999", False)])
def test_min_volume_regular_session(volume, ok):
    result, _ = scan(row({col.VOLUME: volume, col.AVERAGE_VOLUME: "100"}),
                     in_play=InPlayConfig(min_cumulative_volume=2_000_000))
    r = result.candidates[0].result
    assert r.qualified is ok
    check = next(ch for ch in r.hard_checks if ch.name == "min_cumulative_volume")
    assert check.status is (CheckStatus.PASS if ok else CheckStatus.FAIL)


def test_premarket_scan_uses_premarket_threshold():
    config = InPlayConfig(min_cumulative_volume=10_000_000, min_premarket_cumulative_volume=1_000_000)
    result, _ = scan(QUALIFIES, in_play=config, at=T_PREMARKET)
    r = result.candidates[0].result
    names = {ch.name for ch in r.hard_checks}
    assert "min_premarket_cumulative_volume" in names
    assert "min_cumulative_volume" not in names
    assert r.qualified  # 4M >= 1M premarket; the 10M regular threshold does not apply


def test_end_to_end_with_real_client_and_mocked_http():
    clock = FakeClock()
    session = FakeSession(FakeResponse(429, ""), FakeResponse(200, csv_text(QUALIFIES, NO_PRICE)))
    client = FinvizClient(FAKE_KEY, session=session, sleep=clock.sleep,
                          limiter=SlidingWindowRateLimiter(clock=clock, sleep=clock.sleep))
    result = run_in_play_scan(client, clock=lambda: T_REGULAR)
    assert [c.record.ticker for c in result.qualified] == ["ABCD"]
    assert len(result.rejected) == 1
    assert clock.sleeps == [5.0]


# --- CLI ---------------------------------------------------------------------


def run_cli(capsys, argv, client):
    code = cli.main(argv, client=client, clock=lambda: T_REGULAR)
    out, err = capsys.readouterr()
    return code, out, err


def test_cli_prints_qualified_stocks(capsys):
    code, out, err = run_cli(capsys, [], FakeClient(csv_text(QUALIFIES, SMALL_MOVE, NO_PRICE)))
    assert code == 0 and err == ""
    assert "no orders are placed" in out
    assert "NOT a trade signal" in out
    assert "quote freshness UNKNOWN" in out
    assert "REGULAR session" in out
    assert "qualified 1" in out
    assert "ABCD" in out and "+30.0%" in out and "4,000,000" in out
    assert "row 3 IJKL: Price is missing" in out
    assert "EFGH" not in out  # not-qualified stocks hidden without --show-all
    assert FAKE_KEY not in out


def test_cli_applies_default_min_volume(capsys):
    client = FakeClient(csv_text(row({col.VOLUME: "499999", col.AVERAGE_VOLUME: "50"})))
    code, out, _ = run_cli(capsys, ["--show-all"], client)
    assert code == 0
    assert "qualified 0" in out
    assert "session volume 499,999 < min 500,000" in out


def test_cli_min_volume_zero_disables(capsys):
    client = FakeClient(csv_text(row({col.VOLUME: "499999", col.AVERAGE_VOLUME: "50"})))
    _, out, _ = run_cli(capsys, ["--min-volume", "0"], client)
    assert "qualified 1" in out and "regular=-" in out


def test_cli_show_all_lists_reasons(capsys):
    _, out, _ = run_cli(capsys, ["--show-all"], FakeClient(csv_text(SMALL_MOVE)))
    assert "NOT QUALIFIED" in out and "EFGH" in out and "% change" in out


def test_cli_tickers_replace_discovery_filters(capsys):
    client = FakeClient(csv_text(QUALIFIES))
    run_cli(capsys, ["--tickers", "ABCD,EFGH"], client)
    assert client.configs == [FinvizScreenConfig(filters=(), tickers=("ABCD", "EFGH"))]


def test_cli_bad_ticker_is_usage_error(capsys):
    code, _, err = run_cli(capsys, ["--tickers", "abc&auth=x"], FakeClient(""))
    assert code == 2 and "malformed tickers" in err


def test_cli_missing_credentials(capsys):
    # No injected client: from_env runs, and conftest guarantees no key is available.
    code = cli.main([])
    out, err = capsys.readouterr()
    assert code == 2
    assert "FINVIZ_API_KEY is not set" in err and ".env.example" in err
    assert out == ""


def test_cli_api_error_is_reported_safely(capsys):
    code, out, err = run_cli(capsys, [], FakeClient(error=FinvizAuthError("Finviz rejected the API key (HTTP 401)")))
    assert code == 1 and "HTTP 401" in err and out == ""


def test_cli_verbose_prints_warnings(capsys):
    _, out, _ = run_cli(capsys, ["--verbose"], FakeClient(csv_text(QUALIFIES)))
    assert "ABCD: catalyst unknown" in out
