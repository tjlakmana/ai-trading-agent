"""Scanner runs: summaries, classified rows, full row detail, replay."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api import config_meta, schemas, views
from api.deps import history, require_history, utc_now
from memory import serialize as ser
from memory.classification import ScanClass
from memory.scan_store import HistoryIntegrityError, ScanStore

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _resolve(store: ScanStore, run_id: str) -> str:
    try:
        return store.resolve_run_id(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no scan run matches {run_id!r}") from None


def _payload(store: ScanStore, run_id: str) -> dict:
    try:
        return store.load_payload(run_id)
    except ValueError as exc:  # failed run: no payload
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except HistoryIntegrityError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from None


@router.get("", response_model=list[schemas.RunOut])
def list_runs(request: Request, store=Depends(history),
              limit: int = Query(50, ge=1, le=500), profile: str | None = None,
              status: Literal["OK", "ERROR"] | None = None, before: datetime | None = None):
    if store is None:
        return []
    if before is not None and before.tzinfo is None:
        raise HTTPException(status_code=400, detail="before must include a UTC offset")
    now = utc_now(request)
    return [views.run_view(r, now) for r in store.list_runs(limit, profile=profile, status=status,
                                                              before=before)]


@router.get("/latest", response_model=schemas.RunOut)
def latest_run(request: Request, store=Depends(history), profile: str | None = None):
    run = require_history(store).latest_run(profile)
    if run is None:
        raise HTTPException(status_code=404, detail="No successful scan recorded"
                            + (f" for profile {profile!r}" if profile else ""))
    return views.run_view(run, utc_now(request))


@router.get("/{run_id}", response_model=schemas.RunOut)
def get_run(run_id: str, request: Request, store=Depends(history)):
    store = require_history(store)
    return views.run_view(store.get_run(_resolve(store, run_id)), utc_now(request))


@router.get("/{run_id}/rows", response_model=schemas.RowsPageOut)
def list_rows(run_id: str, store=Depends(history),
              status: list[Literal["QUALIFIED", "NEAR_MISS", "FILTERED_OUT", "REJECTED"]] | None = Query(None),
              ticker: str | None = Query(None, max_length=10, pattern=r"^[A-Za-z0-9.\-]+$"),
              sort: str = "pct_change", order: Literal["asc", "desc"] = "desc",
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    store = require_history(store)
    run = store.get_run(_resolve(store, run_id))
    entries = views.all_entries(_payload(store, run.run_id))
    try:
        selected = views.select_rows([views.row_view(e) for e in entries],
                                     statuses=set(status) if status else None,
                                     ticker=ticker.upper() if ticker else None,
                                     sort=sort, descending=order == "desc")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {"run_id": run.run_id, "total": len(selected), "offset": offset, "limit": limit,
            "counts": views.counts(run), "items": selected[offset:offset + limit]}


@router.get("/{run_id}/rows/{row_number}", response_model=schemas.RowDetailOut)
def get_row(run_id: str, row_number: int, request: Request, store=Depends(history)):
    store = require_history(store)
    rid = _resolve(store, run_id)
    _payload(store, rid)  # maps failed-run and integrity errors
    try:
        entry = store.get_entry(rid, row_number)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from None
    return views.row_detail(entry, utc_now(request))


@router.post("/{run_id}/replay", response_model=schemas.ReplayOut)
def replay(run_id: str, body: schemas.ReplayIn, store=Depends(history)):
    store = require_history(store)
    run = store.get_run(_resolve(store, run_id))
    payload = _payload(store, run.run_id)
    try:
        config, applied = config_meta.apply_overrides(payload["in_play_config"], body.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    items = store.replay(run.run_id, config)
    tally = {k: sum(1 for i in items if i.classification.scan_class is k) for k in ScanClass}
    changed = [
        {"row_number": i.row_number, "ticker": i.ticker, "original_status": i.original_status,
         "status": i.classification.scan_class.value,
         "failed_hard_checks": list(i.classification.failed_hard_checks), "reasons": list(i.result.reasons)}
        for i in items if i.classification.scan_class.value != i.original_status
    ]
    return {
        "run_id": run.run_id, "applied_overrides": applied,
        "in_play_config": ser.in_play_config_to_dict(config),
        "counts": {"rows": run.row_count, "qualified": tally[ScanClass.QUALIFIED],
                   "near_miss": tally[ScanClass.NEAR_MISS], "filtered_out": tally[ScanClass.FILTERED_OUT],
                   "rejected": run.rejected_count},
        "original_counts": views.counts(run),
        "changed": changed,
    }
