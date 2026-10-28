"""Shared fixtures for API tests: temporary history databases built from mocked Finviz CSV."""

from datetime import timedelta

from fastapi.testclient import TestClient

from api.app import create_app
from api.security import DASHBOARD_HEADER
from api.settings import ApiSettings
from data.finviz import schema as col
from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizAuthError
from memory.scan_store import ScanStore
from strategy.in_play_config import InPlayConfig
from tests.finviz_fixtures import T_REGULAR, row
from tests.test_scan_store import make_scan

BASE_URL = "http://127.0.0.1:8000"
NOW = T_REGULAR + timedelta(seconds=90)
WRITE_HEADERS = {DASHBOARD_HEADER: "1", "Origin": "http://localhost:5173"}

QUALIFIES = row()  # ABCD +30%, gap +20%
NEAR_MISS = row({col.TICKER: "EFGH", col.PRICE: "5.20", col.OPEN: "5.10"})  # +4%
FILTERED = row({col.TICKER: "IJKL", col.PRICE: "5.20", col.SHARES_FLOAT: "50.00", col.OPEN: "-"})
REJECTED = row({col.TICKER: "MNOP", col.PREV_CLOSE: "-"})


def build_history(path) -> dict:
    """broad run (4 rows), later strict run (ABCD only), latest failed attempt."""
    with ScanStore(path) as s:
        broad = s.record_scan(make_scan(QUALIFIES, NEAR_MISS, FILTERED, REJECTED,
                                        in_play=InPlayConfig(min_cumulative_volume=500_000)),
                              "broad_v1", started_at=T_REGULAR)
        later = T_REGULAR + timedelta(seconds=30)
        strict = s.record_scan(make_scan(QUALIFIES, at=later), "strict_v1", started_at=later)
        failed = s.record_scan_failure(FinvizAuthError("Finviz rejected the API key (HTTP 401)"),
                                       FinvizScreenConfig(), InPlayConfig(), "strict_v1",
                                       started_at=T_REGULAR + timedelta(seconds=60))
    return {"broad": broad, "strict": strict, "failed": failed}


def make_client(db_path, *, finviz_configured=False, **app_kwargs) -> TestClient:
    app = create_app(ApiSettings(db_path=db_path), clock=lambda: NOW,
                     finviz_configured=lambda: finviz_configured, **app_kwargs)
    return TestClient(app, base_url=BASE_URL)
