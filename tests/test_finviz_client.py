"""Tests for data/finviz/client.py. Mocked sessions only; no network."""

import logging
import os
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest
import requests

from data.finviz import schema
from data.finviz.client import (
    DEFAULT_RETRY_AFTER_SECONDS,
    MAX_RETRY_AFTER_SECONDS,
    FinvizClient,
    SlidingWindowRateLimiter,
    _retry_after_seconds,
)
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import (
    FinvizAuthError,
    FinvizCredentialsError,
    FinvizError,
    FinvizHTTPError,
    FinvizNetworkError,
    FinvizRateLimitError,
    FinvizResponseError,
)
from tests.finviz_fixtures import (
    FAKE_KEY,
    FakeClock,
    FakeResponse,
    FakeSession,
    connection_error_with_key,
    csv_text,
    row,
)

SCREEN = FinvizScreenConfig()
OK = FakeResponse(200, csv_text(row()))


def client(*outcomes, clock=None, **kwargs):
    clock = clock or FakeClock()
    session = FakeSession(*outcomes)
    limiter = SlidingWindowRateLimiter(clock=clock, sleep=clock.sleep)
    c = FinvizClient(FAKE_KEY, session=session, limiter=limiter, sleep=clock.sleep, **kwargs)
    return c, session, clock


def assert_no_secret(text: str):
    assert FAKE_KEY not in text
    assert "auth=" + FAKE_KEY[:4] not in text


# --- Credentials -------------------------------------------------------------


def test_from_env_without_key_raises_before_any_request(tmp_path):
    with pytest.raises(FinvizCredentialsError, match="FINVIZ_API_KEY is not set"):
        FinvizClient.from_env(env_file=tmp_path / "missing.env", environ={})


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_blank_key_rejected(value, tmp_path):
    with pytest.raises(FinvizCredentialsError):
        FinvizClient.from_env(env_file=tmp_path / "missing.env", environ={"FINVIZ_API_KEY": value})


@pytest.mark.parametrize("value", ["abc def", "abc&f=x", "abc?x", "a=b", "abc#frag"])
def test_malformed_key_rejected_without_echoing_it(value):
    with pytest.raises(FinvizCredentialsError) as exc:
        FinvizClient(value)
    assert value not in str(exc.value)


@pytest.mark.parametrize("value", [None, 12345, b"bytes"])
def test_non_string_key_rejected(value):
    with pytest.raises(FinvizCredentialsError):
        FinvizClient(value)


def test_from_env_reads_dotenv_file_without_touching_os_environ(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(f"# local\nFINVIZ_API_KEY={FAKE_KEY}\n", encoding="utf-8")
    c = FinvizClient.from_env(env_file=env_file, environ={}, session=FakeSession())
    assert c._api_key == FAKE_KEY
    assert "FINVIZ_API_KEY" not in os.environ


def test_process_environment_wins_over_dotenv(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FINVIZ_API_KEY=from-file\n", encoding="utf-8")
    c = FinvizClient.from_env(env_file=env_file, environ={"FINVIZ_API_KEY": "from-env"})
    assert c._api_key == "from-env"


def test_empty_placeholder_in_dotenv_is_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FINVIZ_API_KEY=\n", encoding="utf-8")
    with pytest.raises(FinvizCredentialsError):
        FinvizClient.from_env(env_file=env_file, environ={})


def test_default_env_file_is_redirected_in_tests():
    # conftest points DEFAULT_ENV_FILE at a non-existent file, so the real .env is never read.
    with pytest.raises(FinvizCredentialsError):
        FinvizClient.from_env()


def test_repr_and_str_hide_key():
    c, _, _ = client()
    assert_no_secret(repr(c))
    assert_no_secret(str(c))
    assert "***" in repr(c)


# --- Request construction ----------------------------------------------------


def test_request_uses_verified_endpoint_params_and_timeout():
    c, session, _ = client(OK, timeout=7.5)
    c.fetch_screener_csv(SCREEN)
    call = session.calls[0]
    assert call["url"] == schema.ENDPOINT
    assert call["timeout"] == 7.5
    assert call["params"]["auth"] == FAKE_KEY
    assert call["params"]["type"] == "stocks"
    assert call["params"]["v"] == "152"
    assert call["params"]["f"] == ",".join(SCREEN.filters)
    assert set(call["params"]["c"].split(",")) == {str(i) for i in schema.COLUMNS}


def test_successful_response_returns_text():
    c, _, _ = client(OK)
    assert c.fetch_screener_csv(SCREEN).startswith("Ticker,Company")


def test_utf8_bom_is_removed():
    c, _, _ = client(FakeResponse(200, "\ufeff" + csv_text(row())))
    assert c.fetch_screener_csv(SCREEN).startswith("Ticker")


def test_content_type_with_charset_accepted():
    c, _, _ = client(FakeResponse(200, csv_text(row()), content_type="text/csv; charset=utf-8"))
    assert c.fetch_screener_csv(SCREEN)


@pytest.mark.parametrize("bad", [0, -1])
def test_timeout_must_be_positive(bad):
    with pytest.raises(ValueError):
        FinvizClient(FAKE_KEY, timeout=bad)


# --- HTTP errors -------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures(status):
    c, _, _ = client(FakeResponse(status, "denied", content_type="text/html"))
    with pytest.raises(FinvizAuthError) as exc:
        c.fetch_screener_csv(SCREEN)
    assert_no_secret(str(exc.value))


@pytest.mark.parametrize("status", [400, 404, 500, 502, 503])
def test_other_http_errors(status):
    c, _, _ = client(FakeResponse(status, "oops", content_type="text/html"))
    with pytest.raises(FinvizHTTPError) as exc:
        c.fetch_screener_csv(SCREEN)
    assert exc.value.status == status
    assert str(status) in str(exc.value)


def test_html_page_with_200_rejected():
    # e.g. a login page served instead of CSV
    c, _, _ = client(FakeResponse(200, "<html>Login</html>", content_type="text/html"))
    with pytest.raises(FinvizResponseError, match="expected text/csv"):
        c.fetch_screener_csv(SCREEN)


def test_missing_content_type_rejected():
    response = FakeResponse(200, csv_text(row()))
    del response.headers["Content-Type"]
    c, _, _ = client(response)
    with pytest.raises(FinvizResponseError):
        c.fetch_screener_csv(SCREEN)


def test_oversized_response_rejected():
    c, _, _ = client(FakeResponse(200, "x" * 101), max_response_bytes=100)
    with pytest.raises(FinvizResponseError, match="too large"):
        c.fetch_screener_csv(SCREEN)


def test_invalid_utf8_rejected():
    c, _, _ = client(FakeResponse(200, b"Ticker\n\xff\xfe\xfa"))
    with pytest.raises(FinvizResponseError, match="UTF-8"):
        c.fetch_screener_csv(SCREEN)


# --- Network failures --------------------------------------------------------


def test_timeout_raises_network_error():
    c, _, _ = client(requests.Timeout("read timed out"), timeout=3)
    with pytest.raises(FinvizNetworkError, match="timed out after 3s"):
        c.fetch_screener_csv(SCREEN)


@pytest.mark.parametrize("exc", [connection_error_with_key(), requests.exceptions.SSLError("cert"),
                                 requests.TooManyRedirects("loop")])
def test_request_exceptions_never_leak_url_or_key(exc):
    c, _, _ = client(exc)
    with pytest.raises(FinvizNetworkError) as caught:
        c.fetch_screener_csv(SCREEN)
    assert_no_secret(str(caught.value))
    # Raised outside the except block: no chained exception carrying the URL.
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_all_errors_share_a_base_class():
    for cls in (FinvizAuthError, FinvizCredentialsError, FinvizHTTPError, FinvizNetworkError,
                FinvizRateLimitError, FinvizResponseError):
        assert issubclass(cls, FinvizError)


# --- HTTP 429 handling -------------------------------------------------------


def test_429_retries_after_retry_after_header():
    c, session, clock = client(FakeResponse(429, "", headers={"Retry-After": "3"}), OK)
    assert c.fetch_screener_csv(SCREEN)
    assert len(session.calls) == 2
    assert clock.sleeps == [3.0]


def test_429_without_header_waits_documented_default():
    c, _, clock = client(FakeResponse(429, ""), OK)
    c.fetch_screener_csv(SCREEN)
    assert clock.sleeps == [DEFAULT_RETRY_AFTER_SECONDS] == [5.0]


def test_429_persisting_raises_after_bounded_retries():
    c, session, clock = client(*[FakeResponse(429, "", headers={"Retry-After": "1"})] * 3)
    with pytest.raises(FinvizRateLimitError, match="after 2 retries"):
        c.fetch_screener_csv(SCREEN)
    assert len(session.calls) == 3
    assert clock.sleeps == [1.0, 1.0]


def test_429_with_retries_disabled_fails_immediately():
    c, session, clock = client(FakeResponse(429, ""), max_rate_limit_retries=0)
    with pytest.raises(FinvizRateLimitError):
        c.fetch_screener_csv(SCREEN)
    assert len(session.calls) == 1
    assert clock.sleeps == []


@pytest.mark.parametrize("value, expected", [
    (None, DEFAULT_RETRY_AFTER_SECONDS), ("", DEFAULT_RETRY_AFTER_SECONDS),
    ("2", 2.0), ("2.5", 2.5), ("0", 0.0), ("-4", 0.0),
    ("9999", MAX_RETRY_AFTER_SECONDS), ("soon", DEFAULT_RETRY_AFTER_SECONDS),
    ("nan", DEFAULT_RETRY_AFTER_SECONDS),
])
def test_retry_after_parsing(value, expected):
    assert _retry_after_seconds(value) == expected


def test_retry_after_http_date():
    when = datetime.now(timezone.utc) + timedelta(seconds=10)
    assert 8 <= _retry_after_seconds(format_datetime(when, usegmt=True)) <= 10


def test_429_retry_logs_contain_no_secret(caplog):
    caplog.set_level(logging.DEBUG)
    c, _, _ = client(FakeResponse(429, ""), OK)
    c.fetch_screener_csv(SCREEN)
    assert "rate limited" in caplog.text
    assert_no_secret(caplog.text)


def test_urllib3_debug_log_is_redacted(caplog):
    caplog.set_level(logging.DEBUG)
    logging.getLogger("urllib3.connectionpool").debug(
        '%s://%s:%s "%s %s %s" %s %s', "https", "elite.finviz.com", 443, "GET",
        f"/export/screener?type=stocks&auth={FAKE_KEY}&f=sh_float_u20", "HTTP/1.1", 200, None,
    )
    assert_no_secret(caplog.text)
    assert "auth=***" in caplog.text
    assert "f=sh_float_u20" in caplog.text


# --- Client-side rate limiter ------------------------------------------------


def test_limiter_allows_ten_requests_per_five_seconds():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(clock=clock, sleep=clock.sleep)
    for _ in range(10):
        limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()  # 11th must wait for the oldest to leave the window
    assert clock.sleeps == [pytest.approx(5.0)]


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = SlidingWindowRateLimiter(max_requests=2, window_seconds=5.0, clock=clock, sleep=clock.sleep)
    limiter.acquire()
    clock.now += 3
    limiter.acquire()
    clock.now += 2.5  # first request is now 5.5s old, second 2.5s old
    limiter.acquire()
    assert clock.sleeps == []
    limiter.acquire()  # must wait until the second request (at t+3) is 5s old
    assert clock.sleeps == [pytest.approx(2.5)]


def test_client_paces_every_request_including_retries():
    clock = FakeClock()
    calls = []

    class CountingLimiter:
        def acquire(self):
            calls.append(clock.now)

    c = FinvizClient(FAKE_KEY, session=FakeSession(FakeResponse(429, ""), OK),
                     limiter=CountingLimiter(), sleep=clock.sleep)
    c.fetch_screener_csv(SCREEN)
    assert len(calls) == 2


@pytest.mark.parametrize("kwargs", [{"max_requests": 0}, {"max_requests": 1.5}, {"window_seconds": 0}])
def test_limiter_rejects_bad_settings(kwargs):
    with pytest.raises(ValueError):
        SlidingWindowRateLimiter(**kwargs)
