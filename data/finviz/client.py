"""HTTP client for the Finviz Elite Screener export API.

Security:
- The API key comes only from FINVIZ_API_KEY (process environment first, then
  the project's .env via python-dotenv). It is never hard-coded.
- The key is sent as Finviz's required `auth` query parameter, so the
  authenticated URL is a secret. It never appears in exceptions, repr, or our
  logs. urllib3's DEBUG request log is redacted, and requests exceptions
  (whose messages contain the URL) are replaced by FinvizError subclasses
  raised outside the except block, so no traceback chains back to them.

Rate limits (Finviz Elite: 10 requests per rolling 5 seconds per account,
shared across all export endpoints): a client-side sliding-window limiter
paces requests. HTTP 429 is retried after Retry-After (default 5 seconds,
capped), a bounded number of times.
"""

import logging
import os
import re
import time
from collections import deque
from collections.abc import Callable, Mapping
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from dotenv import dotenv_values

from data.finviz.config import FinvizScreenConfig, screener_params
from data.finviz.errors import (
    FinvizAuthError,
    FinvizCredentialsError,
    FinvizHTTPError,
    FinvizNetworkError,
    FinvizRateLimitError,
    FinvizResponseError,
)
from data.finviz.schema import API_KEY_ENV_VAR, ENDPOINT

log = logging.getLogger(__name__)

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_TIMEOUT_SECONDS = 10.0
RATE_LIMIT_REQUESTS = 10
RATE_LIMIT_WINDOW_SECONDS = 5.0
DEFAULT_RETRY_AFTER_SECONDS = 5.0  # documented Finviz Retry-After
MAX_RETRY_AFTER_SECONDS = 30.0
MAX_RATE_LIMIT_RETRIES = 2
MAX_RESPONSE_BYTES = 20_000_000

_AUTH_PARAM = re.compile(r"(auth=)[^&\s\"']+", re.IGNORECASE)


class _RedactAuthFilter(logging.Filter):
    """Masks auth=<value> in log records (urllib3 logs request paths at DEBUG)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if "auth=" in message.lower():
            record.msg = _AUTH_PARAM.sub(r"\1***", message)
            record.args = None
        return True


def _install_log_redaction() -> None:
    for name in ("urllib3.connectionpool", "urllib3"):
        logger = logging.getLogger(name)
        if not any(isinstance(f, _RedactAuthFilter) for f in logger.filters):
            logger.addFilter(_RedactAuthFilter())


_install_log_redaction()


class SlidingWindowRateLimiter:
    """Allows at most max_requests in any rolling window_seconds."""

    def __init__(self, max_requests: int = RATE_LIMIT_REQUESTS,
                 window_seconds: float = RATE_LIMIT_WINDOW_SECONDS,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        if not isinstance(max_requests, int) or max_requests < 1:
            raise ValueError("max_requests must be a positive whole number")
        if not window_seconds > 0:
            raise ValueError("window_seconds must be positive")
        self._max = max_requests
        self._window = window_seconds
        self._clock = clock
        self._sleep = sleep
        self._sent: deque[float] = deque()

    def acquire(self) -> None:
        """Block until a request may be sent, then record it."""
        while True:
            now = self._clock()
            while self._sent and self._sent[0] <= now - self._window:
                self._sent.popleft()
            if len(self._sent) < self._max:
                self._sent.append(now)
                return
            self._sleep(self._sent[0] + self._window - now)


def _retry_after_seconds(value: str | None) -> float:
    """Parse Retry-After (seconds or HTTP date), clamped to [0, MAX_RETRY_AFTER_SECONDS]."""
    if value is None or not value.strip():
        return DEFAULT_RETRY_AFTER_SECONDS
    value = value.strip()
    try:
        seconds = float(value)
    except ValueError:
        try:
            when = parsedate_to_datetime(value)
            seconds = when.timestamp() - time.time()
        except (TypeError, ValueError, OverflowError):
            return DEFAULT_RETRY_AFTER_SECONDS
    if seconds != seconds:  # NaN
        return DEFAULT_RETRY_AFTER_SECONDS
    return min(max(seconds, 0.0), MAX_RETRY_AFTER_SECONDS)


def _read_api_key(env_file: Path | None, environ: Mapping[str, str] | None) -> str | None:
    """FINVIZ_API_KEY from the environment, else from env_file (None = project .env)."""
    environ = os.environ if environ is None else environ
    env_file = DEFAULT_ENV_FILE if env_file is None else env_file
    key = environ.get(API_KEY_ENV_VAR)
    if (not key or not key.strip()) and Path(env_file).is_file():
        key = dotenv_values(env_file).get(API_KEY_ENV_VAR)
    return key


def api_key_configured(env_file: Path | None = None, environ: Mapping[str, str] | None = None) -> bool:
    """True if a well-formed FINVIZ_API_KEY is available. Never returns or logs the key."""
    try:
        _validate_api_key(_read_api_key(env_file, environ))
    except FinvizCredentialsError:
        return False
    return True


def _validate_api_key(api_key) -> str:
    if not isinstance(api_key, str) or not api_key.strip():
        raise FinvizCredentialsError(f"{API_KEY_ENV_VAR} is not set (environment or .env)")
    key = api_key.strip()
    if any(ch.isspace() for ch in key) or any(ch in key for ch in "&=?#"):
        raise FinvizCredentialsError(f"{API_KEY_ENV_VAR} is malformed (contains spaces or URL characters)")
    return key


class FinvizClient:
    """Fetches Finviz screener CSV. Knows nothing about strategy or trading."""

    def __init__(self, api_key: str, *, session=None,
                 timeout: float = DEFAULT_TIMEOUT_SECONDS,
                 max_rate_limit_retries: int = MAX_RATE_LIMIT_RETRIES,
                 limiter: SlidingWindowRateLimiter | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 max_response_bytes: int = MAX_RESPONSE_BYTES):
        self._api_key = _validate_api_key(api_key)
        if not timeout > 0:
            raise ValueError("timeout must be positive")
        if not isinstance(max_rate_limit_retries, int) or max_rate_limit_retries < 0:
            raise ValueError("max_rate_limit_retries must be a whole number >= 0")
        self._session = session if session is not None else requests.Session()
        self._timeout = timeout
        self._max_retries = max_rate_limit_retries
        self._limiter = limiter if limiter is not None else SlidingWindowRateLimiter()
        self._sleep = sleep
        self._max_bytes = max_response_bytes

    @classmethod
    def from_env(cls, env_file: Path | None = None,
                 environ: Mapping[str, str] | None = None, **kwargs) -> "FinvizClient":
        """Build a client from FINVIZ_API_KEY.

        The process environment wins; otherwise the key is read from env_file
        (None means the project .env, DEFAULT_ENV_FILE). os.environ is not modified.
        """
        return cls(_read_api_key(env_file, environ), **kwargs)

    def __repr__(self) -> str:
        return f"FinvizClient(api_key=***, timeout={self._timeout})"

    def fetch_screener_csv(self, config: FinvizScreenConfig) -> str:
        """Run one screen and return the CSV text. Raises FinvizError subclasses."""
        params = screener_params(config)
        attempt = 0
        while True:
            self._limiter.acquire()
            response, failure = None, None
            try:
                response = self._session.get(ENDPOINT, params={**params, "auth": self._api_key},
                                             timeout=self._timeout)
            except requests.Timeout:
                failure = f"Finviz request timed out after {self._timeout:g}s"
            except requests.RequestException as exc:  # message would contain the URL
                failure = f"Finviz request failed: {type(exc).__name__}"
            if failure is not None:
                raise FinvizNetworkError(failure)

            status = response.status_code
            if status == 429:
                if attempt >= self._max_retries:
                    raise FinvizRateLimitError(f"Finviz rate limit (HTTP 429) persisted after {attempt} retries")
                wait = _retry_after_seconds(response.headers.get("Retry-After"))
                attempt += 1
                log.warning("Finviz rate limited (HTTP 429); retry %d/%d in %.1fs",
                            attempt, self._max_retries, wait)
                self._sleep(wait)
                continue
            if status in (401, 403):
                raise FinvizAuthError(f"Finviz rejected the API key (HTTP {status})")
            if status != 200:
                raise FinvizHTTPError(status)
            return self._csv_text(response)

    def _csv_text(self, response) -> str:
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if content_type != "text/csv":
            raise FinvizResponseError(f"expected text/csv, got {content_type or 'no content type'!r}")
        body = response.content
        if len(body) > self._max_bytes:
            raise FinvizResponseError(f"response too large ({len(body):,} bytes)")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise FinvizResponseError("response is not valid UTF-8") from None
        log.info("Finviz screen returned %d bytes", len(body))
        return text
