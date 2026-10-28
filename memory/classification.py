"""Read-side classification of in-play results for history and dashboards.

    QUALIFIED     every HARD check passed (result.qualified)
    NEAR_MISS     valid data and exactly one HARD check did not pass
                  (FAIL, or UNKNOWN because data was missing)
    FILTERED_OUT  everything else, including snapshots with invalid data

This is a view over the deterministic strategy's output. It never changes
which stocks qualify, and NEAR_MISS is not a trade signal. Rows that could
not be normalized into a snapshot are stored separately as REJECTED.
"""

from dataclasses import dataclass
from enum import Enum

from strategy.in_play import CheckStatus, InPlayResult

NEAR_MISS_MAX_HARD_FAILURES = 1


class ScanClass(str, Enum):
    QUALIFIED = "QUALIFIED"
    NEAR_MISS = "NEAR_MISS"
    FILTERED_OUT = "FILTERED_OUT"


@dataclass(frozen=True)
class Classification:
    scan_class: ScanClass
    failed_hard_checks: tuple[str, ...]  # names of HARD checks that did not pass
    hard_failures: int | None  # None when the snapshot data was invalid


def classify(result: InPlayResult) -> Classification:
    if not isinstance(result, InPlayResult):
        raise TypeError(f"expected InPlayResult, got {type(result).__name__}")
    if not result.valid_data:
        return Classification(ScanClass.FILTERED_OUT, ("invalid_data",), None)
    failed = tuple(c.name for c in result.hard_checks if c.status is not CheckStatus.PASS)
    if result.qualified:
        scan_class = ScanClass.QUALIFIED
    elif len(failed) <= NEAR_MISS_MAX_HARD_FAILURES:
        scan_class = ScanClass.NEAR_MISS
    else:
        scan_class = ScanClass.FILTERED_OUT
    return Classification(scan_class, failed, len(failed))
