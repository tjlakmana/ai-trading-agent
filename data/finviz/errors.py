"""Finviz provider errors.

Messages are safe to print and log: they never contain the API key, the
request URL, or the query string.
"""


class FinvizError(Exception):
    """Base class for every Finviz provider failure."""


class FinvizCredentialsError(FinvizError):
    """FINVIZ_API_KEY is missing or malformed. No request was sent."""


class FinvizAuthError(FinvizError):
    """Finviz rejected the API key (HTTP 401/403)."""


class FinvizRateLimitError(FinvizError):
    """Still rate limited (HTTP 429) after the allowed retries."""


class FinvizHTTPError(FinvizError):
    """Any other non-200 HTTP status."""

    def __init__(self, status: int):
        super().__init__(f"Finviz returned HTTP {status}")
        self.status = status


class FinvizNetworkError(FinvizError):
    """Timeout, connection, or TLS failure before a response arrived."""


class FinvizResponseError(FinvizError):
    """The response is not the CSV we expect (wrong type, too large, bad header)."""
