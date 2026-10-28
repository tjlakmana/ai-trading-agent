"""Mocked Finviz responses for tests. No network, no real credentials."""

import csv
import io
from datetime import datetime, timezone

import requests
from requests.structures import CaseInsensitiveDict

from data.finviz import schema as col

FAKE_KEY = "test-key-NOT-REAL-0123456789"
HEADERS = [col.COLUMNS[i] for i in sorted(col.COLUMNS)]

T_REGULAR = datetime(2026, 10, 28, 18, 21, tzinfo=timezone.utc)  # Wed 14:21 EDT
T_PREMARKET = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)  # Wed 08:00 EDT
T_AFTER_HOURS = datetime(2026, 10, 28, 21, 0, tzinfo=timezone.utc)  # Wed 17:00 EDT

# An ideal V1 candidate in Finviz's raw format: +30%, 8x average volume, 6M float.
BASE_ROW = {
    col.TICKER: "ABCD", col.COMPANY: "Abcd Therapeutics Inc", col.EXCHANGE: "NASD",
    col.PRICE: "6.50", col.PREV_CLOSE: "5.00", col.OPEN: "6.00",
    col.HIGH: "6.80", col.LOW: "5.90", col.VOLUME: "4000000",
    col.AVERAGE_VOLUME: "500.00", col.SHARES_FLOAT: "6.00", col.TRADES: "12000",
    col.RELATIVE_VOLUME: "9.50", col.CHANGE: "30.00%", col.CHANGE_FROM_OPEN: "8.33%",
    col.GAP: "20.00%", col.PERF_1M: "0.50%", col.PERF_5M: "1.20%", col.PERF_10M: "2.00%",
    col.PERF_15M: "3.10%", col.PERF_30M: "4.00%", col.PERF_1H: "6.00%",
    col.NEWS_TIME: "2026-10-28 08:00:00", col.NEWS_TITLE: "Abcd announces FDA approval",
}


def row(changes: dict | None = None) -> dict[str, str]:
    """BASE_ROW with some cells changed, keyed by Finviz header name."""
    return {**BASE_ROW, **(changes or {})}


def csv_text(*rows: dict, headers: list[str] | None = None) -> str:
    headers = HEADERS if headers is None else headers
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\r\n")
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r.get(h, "") for h in headers])
    return out.getvalue()


class FakeResponse:
    def __init__(self, status: int = 200, body: str | bytes = "", content_type: str = "text/csv",
                 headers: dict | None = None):
        self.status_code = status
        self.content = body.encode("utf-8") if isinstance(body, str) else body
        self.headers = CaseInsensitiveDict({"Content-Type": content_type, **(headers or {})})


class FakeSession:
    """Replays queued responses (or raises queued exceptions) and records calls."""

    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeClient:
    """Stands in for FinvizClient in scan/CLI tests."""

    def __init__(self, text: str | None = None, error: Exception | None = None):
        self.text, self.error, self.configs = text, error, []

    def fetch_screener_csv(self, config):
        self.configs.append(config)
        if self.error is not None:
            raise self.error
        return self.text


def connection_error_with_key() -> requests.ConnectionError:
    """A requests error whose message contains the authenticated URL, like the real ones."""
    return requests.ConnectionError(
        f"HTTPSConnectionPool(host='elite.finviz.com', port=443): Max retries exceeded with url: "
        f"/export/screener?type=stocks&auth={FAKE_KEY}"
    )
