"""FastAPI application factory.

create_app() wires settings, the shared payload cache, the guarded scan
coordinator and the routers. Dependencies are injectable for tests:
clock, finviz_configured, client_factory (Finviz client), scan_launcher and
monotonic (scan threading and cooldown timing).
"""

import time
from collections.abc import Callable
from datetime import datetime, timezone

from fastapi import FastAPI

from api.routes import meta, runs, scans, tickers
from api.scan_jobs import ScanCoordinator, thread_launcher
from api.security import LocalOnlyMiddleware
from api.settings import ApiSettings
from data.finviz.client import FinvizClient
from memory.scan_store import PayloadCache


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def create_app(settings: ApiSettings | None = None, *,
               clock: Callable[[], datetime] = _utc_now,
               finviz_configured: Callable[[], bool] = meta.default_finviz_configured,
               client_factory: Callable[[], object] = FinvizClient.from_env,
               scan_launcher: Callable[[Callable[[], None]], None] = thread_launcher,
               monotonic: Callable[[], float] = time.monotonic) -> FastAPI:
    settings = ApiSettings() if settings is None else settings
    app = FastAPI(
        title="AI Trading Agent - Dashboard API",
        version=meta.API_VERSION,
        description="Local, research-only viewer over Finviz scanner history. No order execution.",
    )
    app.state.settings = settings
    app.state.clock = clock
    app.state.finviz_configured = finviz_configured
    app.state.payload_cache = PayloadCache(settings.payload_cache_runs)
    app.state.scans = ScanCoordinator(db_path=settings.db_path, client_factory=client_factory, clock=clock,
                                      cooldown_seconds=settings.scan_cooldown_seconds,
                                      monotonic=monotonic, launcher=scan_launcher)
    app.add_middleware(LocalOnlyMiddleware, settings=settings)
    for router in (meta.router, runs.router, tickers.router, scans.router):
        app.include_router(router)
    return app
