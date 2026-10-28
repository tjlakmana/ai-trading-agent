"""Response and request models (the API contract the frontend's types are generated from).

Origin of every number is explicit:
    market      raw Finviz inputs, units converted (dollars, shares)
    calculated  our deterministic metrics (strategy/ or this API)
    vendor      Finviz-calculated values: discovery only, never used in our checks
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, StrictFloat, StrictInt, StrictStr

RowStatus = Literal["QUALIFIED", "NEAR_MISS", "FILTERED_OUT", "REJECTED"]
Freshness = Literal["UNKNOWN", "VERIFIED"]


class FreshnessOut(BaseModel):
    fetched_at: datetime | None = Field(description="When we received the Finviz response (UTC)")
    fetched_at_et: str | None = Field(description="fetched_at in US Eastern time")
    quote_time: datetime | None = Field(None, description="Market timestamp of the quotes; Finviz provides none")
    quote_freshness: Freshness
    seconds_since_fetch: float | None = Field(description="Age of the fetch, NOT of the quotes")
    note: str


class ErrorOut(BaseModel):
    type: str
    message: str


class CountsOut(BaseModel):
    rows: int
    qualified: int
    near_miss: int
    filtered_out: int
    rejected: int


class RunOut(BaseModel):
    run_id: str
    short_id: str
    profile: str
    status: Literal["OK", "ERROR"]
    provider: str
    started_at: datetime
    recorded_at: datetime
    session: str | None
    counts: CountsOut
    error: ErrorOut | None
    screen_config: dict
    in_play_config: dict
    payload_sha256: str | None
    freshness: FreshnessOut


class MarketOut(BaseModel):
    price: float | None
    previous_close: float | None
    open_price: float | None
    day_high: float | None
    day_low: float | None
    cumulative_volume: int | None
    average_daily_volume: float | None
    float_shares: int | None
    trades: int | None


class CalculatedOut(BaseModel):
    pct_change: float | None
    gap_pct: float | None
    volume_vs_avg_daily: float | None = Field(description="Partial session volume / average FULL-DAY "
                                                          "volume. Not time-of-day RVOL.")
    room_to_resistance_pct: float | None
    pct_below_day_high: float | None = Field(description="(day high - price) / day high at fetch time. "
                                                         "A snapshot, not a real-time alert.")


class VendorOut(BaseModel):
    relative_volume: float | None
    change_pct: float | None
    change_from_open_pct: float | None
    gap_pct: float | None
    perf_1m_pct: float | None
    perf_5m_pct: float | None
    perf_10m_pct: float | None
    perf_15m_pct: float | None
    perf_30m_pct: float | None
    perf_1h_pct: float | None


class NewsOut(BaseModel):
    time: str | None = Field(description="Finviz 'News Time' text, as received (time zone not documented)")
    title: str | None
    classification: Literal["UNCLASSIFIED"] = "UNCLASSIFIED"


class RowOut(BaseModel):
    row_number: int
    ticker: str | None
    company: str | None
    exchange: str | None
    status: RowStatus
    hard_failures: int | None
    failed_hard_checks: list[str]
    reasons: list[str]
    warnings_count: int
    market: MarketOut
    calculated: CalculatedOut
    vendor: VendorOut
    news: NewsOut


class RowsPageOut(BaseModel):
    run_id: str
    total: int
    offset: int
    limit: int
    counts: CountsOut
    items: list[RowOut]


class CheckOut(BaseModel):
    name: str
    level: Literal["HARD", "PREFERRED", "OFF"]
    status: Literal["PASS", "FAIL", "UNKNOWN"]
    actual: int | float | str | None  # int first: share counts stay whole numbers
    threshold: int | float | str | None
    message: str


class RowDetailOut(RowOut):
    qualified: bool | None
    valid_data: bool | None
    hard_checks: list[CheckOut]
    quality_checks: list[CheckOut]
    quality_passed: int | None
    quality_total: int | None
    warnings: list[str]
    normalization_errors: list[str]
    raw: dict[str, str] = Field(description="Unchanged Finviz CSV cells")
    session: str
    freshness: FreshnessOut


class TickerObservationOut(BaseModel):
    run_id: str
    short_id: str
    started_at: datetime
    profile: str
    row_number: int
    status: RowStatus
    failed_hard_checks: list[str]
    price: float | None
    pct_change: float | None
    cumulative_volume: int | None
    volume_vs_avg_daily: float | None
    float_shares: int | None


class TickerHistoryOut(BaseModel):
    ticker: str
    observations: list[TickerObservationOut]


class ProfileOut(BaseModel):
    name: str
    filters: list[dict]
    is_default: bool


class ConfigFieldOut(BaseModel):
    name: str
    kind: Literal["float", "int", "level"]
    nullable: bool
    unit: str
    default: float | int | str | None
    scan_default: float | int | str | None
    description: str


class ModuleOut(BaseModel):
    id: str
    title: str
    status: Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]
    data_source: str
    detail: str


class HealthOut(BaseModel):
    status: Literal["ok"]
    api_version: str
    server_time: datetime
    database_exists: bool
    schema_version: int
    finviz_key_configured: bool
    order_execution_enabled: Literal[False] = False
    trading_mode: Literal["RESEARCH_ONLY"] = "RESEARCH_ONLY"


class ReplayIn(BaseModel):
    # Strict types: JSON true/false must never be coerced into 1/0 thresholds.
    overrides: dict[str, StrictInt | StrictFloat | StrictStr | None] = Field(
        default_factory=dict, description="InPlayConfig fields to change, e.g. {'min_pct_change': 0.2}")


class ReplayChangeOut(BaseModel):
    row_number: int
    ticker: str
    original_status: RowStatus
    status: RowStatus
    failed_hard_checks: list[str]
    reasons: list[str]


class ReplayOut(BaseModel):
    run_id: str
    applied_overrides: dict[str, float | int | str | None]
    in_play_config: dict
    counts: CountsOut
    original_counts: CountsOut
    changed: list[ReplayChangeOut]
    note: str = "Replays are computed on stored snapshots and never written to history."


class ScanIn(BaseModel):
    profile: str


class ScanJobOut(BaseModel):
    job_id: str
    profile: str
    state: Literal["RUNNING", "SUCCEEDED", "FAILED"]
    requested_at: datetime
    finished_at: datetime | None
    run_id: str | None
    error: ErrorOut | None
    counts: CountsOut | None


class ScanStatusOut(BaseModel):
    running: ScanJobOut | None
    latest: ScanJobOut | None
    cooldown_seconds: float
    cooldown_remaining_seconds: float
    finviz_key_configured: bool
