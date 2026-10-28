"""Manual "Run scan now": start one guarded Finviz scan and poll its progress."""

import math

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from api import schemas
from api.scan_jobs import ScanBusyError, ScanCooldownError, UnknownProfileError

router = APIRouter(prefix="/api/scans", tags=["scans"])


@router.post("", response_model=schemas.ScanJobOut, status_code=202)
def start_scan(body: schemas.ScanIn, request: Request):
    try:
        return request.app.state.scans.start(body.profile)
    except UnknownProfileError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except ScanBusyError as exc:
        return JSONResponse(status_code=409, content={
            "detail": "A scan is already running. Showing it instead of starting another.",
            "job": schemas.ScanJobOut(**exc.job).model_dump(mode="json")})
    except ScanCooldownError as exc:
        wait = math.ceil(exc.retry_after)
        return JSONResponse(status_code=429, headers={"Retry-After": str(wait)},
                            content={"detail": f"Scan cooldown: try again in {wait}s.",
                                     "retry_after_seconds": wait})


@router.get("/status", response_model=schemas.ScanStatusOut)
def scan_status(request: Request):
    return {**request.app.state.scans.status(),
            "finviz_key_configured": request.app.state.finviz_configured()}


@router.get("/{job_id}", response_model=schemas.ScanJobOut)
def get_scan(job_id: str, request: Request):
    try:
        return request.app.state.scans.get(job_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown scan job") from None
