"""Request guards for a loopback-only API.

- Host header must be a loopback name (blocks DNS-rebinding attacks from web pages).
- State-changing methods (POST, ...) need the X-Dashboard-Request header,
  which a cross-site page cannot send without a CORS preflight we never
  approve. If an Origin header is present, it must be a local dashboard origin.
- Every response is marked no-store.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from api.settings import ApiSettings, LOOPBACK_HOSTS

DASHBOARD_HEADER = "X-Dashboard-Request"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _host_name(host_header: str) -> str:
    host = host_header.strip().lower()
    if host.startswith("["):  # [::1]:8000
        return host[1:host.find("]")] if "]" in host else host
    return host.rsplit(":", 1)[0] if host.count(":") == 1 else host


class LocalOnlyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: ApiSettings):
        super().__init__(app)
        self._origins = settings.allowed_origins

    async def dispatch(self, request: Request, call_next):
        if _host_name(request.headers.get("host", "")) not in LOOPBACK_HOSTS:
            return JSONResponse({"detail": "the dashboard API only serves localhost"}, status_code=403)
        if request.method not in _SAFE_METHODS:
            if request.headers.get(DASHBOARD_HEADER) != "1":
                return JSONResponse({"detail": f"missing {DASHBOARD_HEADER} header"}, status_code=403)
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._origins:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
