"""Finviz discovery -> deterministic in-play filter.

    client.fetch_screener_csv -> parse_screener_csv -> evaluate_universe -> FinvizScan

Every row is kept: rows that could not be normalized are in `rejected`, and
every normalized row has its InPlayResult (qualified or not) in `candidates`.
"Qualified" only means "proceed to the next strategy stage". It is never a
trade signal, and nothing here can reach bot/ or execution/.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from data.finviz.config import FinvizScreenConfig
from data.finviz.parse import FinvizRecord, QuoteFreshness, parse_screener_csv
from data.market_hours import Session, session_at
from strategy.in_play import InPlayResult, evaluate_universe
from strategy.in_play_config import InPlayConfig


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FinvizCandidate:
    record: FinvizRecord  # raw Finviz row, vendor metrics, fetched_at
    result: InPlayResult  # deterministic evaluation of record.snapshot


@dataclass(frozen=True)
class FinvizScan:
    fetched_at: datetime
    session: Session
    quote_freshness: QuoteFreshness  # always UNKNOWN for Finviz
    screen_config: FinvizScreenConfig
    in_play_config: InPlayConfig
    candidates: tuple[FinvizCandidate, ...]  # every normalized row, in response order
    rejected: tuple[FinvizRecord, ...]  # rows without a snapshot, with their errors

    @property
    def qualified(self) -> tuple[FinvizCandidate, ...]:
        return tuple(c for c in self.candidates if c.result.qualified)

    @property
    def not_qualified(self) -> tuple[FinvizCandidate, ...]:
        return tuple(c for c in self.candidates if not c.result.qualified)

    def age_seconds(self, now: datetime) -> float:
        """Seconds since the response was fetched. Says nothing about quote age."""
        return (now - self.fetched_at).total_seconds()

    def is_stale(self, now: datetime, max_age_seconds: float) -> bool:
        return self.age_seconds(now) > max_age_seconds


def run_in_play_scan(client, screen_config: FinvizScreenConfig | None = None,
                     in_play_config: InPlayConfig | None = None, *,
                     clock: Callable[[], datetime] = _utc_now) -> FinvizScan:
    """Fetch one Finviz screen and evaluate every row with the in-play filter."""
    screen_config = FinvizScreenConfig() if screen_config is None else screen_config
    in_play_config = InPlayConfig() if in_play_config is None else in_play_config
    if not isinstance(screen_config, FinvizScreenConfig):
        raise TypeError(f"screen_config must be a FinvizScreenConfig, got {type(screen_config).__name__}")
    if not isinstance(in_play_config, InPlayConfig):
        raise TypeError(f"in_play_config must be an InPlayConfig, got {type(in_play_config).__name__}")

    text = client.fetch_screener_csv(screen_config)
    fetched_at = clock()  # when the response arrived
    records = parse_screener_csv(text, fetched_at)

    usable = [r for r in records if r.snapshot is not None]
    results = evaluate_universe([r.snapshot for r in usable], in_play_config)
    return FinvizScan(
        fetched_at=fetched_at,
        session=session_at(fetched_at),
        quote_freshness=QuoteFreshness.UNKNOWN,
        screen_config=screen_config,
        in_play_config=in_play_config,
        candidates=tuple(FinvizCandidate(r, res) for r, res in zip(usable, results)),
        rejected=tuple(r for r in records if r.snapshot is None),
    )
