"""Per-request access to scanner history.

Each request opens its own read-only ScanStore (SQLite connections are not
shared across threads). One verified-payload cache is shared app-wide.
"""

from collections.abc import Iterator
from datetime import datetime

from fastapi import HTTPException, Request

from memory.scan_store import ScanStore


def utc_now(request: Request) -> datetime:
    return request.app.state.clock()


def history(request: Request) -> Iterator[ScanStore | None]:
    """A read-only store, or None when no history database exists yet."""
    state = request.app.state
    if not state.settings.db_path.is_file():
        yield None
        return
    try:
        store = ScanStore(state.settings.db_path, read_only=True, payload_cache=state.payload_cache)
    except RuntimeError as exc:  # not initialized / newer schema
        raise HTTPException(status_code=503, detail=str(exc)) from None
    try:
        yield store
    finally:
        store.close()


def require_history(store: ScanStore | None) -> ScanStore:
    if store is None:
        raise HTTPException(status_code=404, detail="No scans recorded yet. Run a scan first.")
    return store
