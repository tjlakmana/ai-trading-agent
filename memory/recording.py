"""Run one Finviz scan and record the attempt (success or failure) in scanner history.

Shared by `python -m data.finviz` and the dashboard API so both record scans
the same way. Recording only: nothing here can reach bot/ or execution/.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from data.finviz.config import FinvizScreenConfig
from data.finviz.errors import FinvizError
from data.finviz.scan import FinvizScan, run_in_play_scan
from memory.scan_store import ScanStore
from strategy.in_play_config import InPlayConfig


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RecordedScan:
    started_at: datetime
    scan: FinvizScan | None  # None when the attempt failed
    error: FinvizError | None  # key-safe; None on success
    run_id: str | None  # None when no store was given

    @property
    def ok(self) -> bool:
        return self.error is None


def run_and_record(client_factory: Callable[[], object], screen: FinvizScreenConfig,
                   in_play: InPlayConfig, profile_name: str, *, store: ScanStore | None = None,
                   clock: Callable[[], datetime] = _utc_now) -> RecordedScan:
    """Create the client, run the scan, and record the outcome.

    Finviz failures (credentials, HTTP, network, response format) are recorded
    as ERROR runs and returned, not raised. Storage errors propagate.
    """
    started_at = clock()
    try:
        client = client_factory()
        scan = run_in_play_scan(client, screen, in_play, clock=clock)
    except FinvizError as exc:
        run_id = None
        if store is not None:
            run_id = store.record_scan_failure(exc, screen, in_play, profile_name, started_at=started_at)
        return RecordedScan(started_at, None, exc, run_id)
    run_id = store.record_scan(scan, profile_name, started_at=started_at) if store is not None else None
    return RecordedScan(started_at, scan, None, run_id)
