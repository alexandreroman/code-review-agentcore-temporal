"""Retry classification of GitHub API errors, shared by the router and the worker activities."""

import time
from collections.abc import Mapping
from dataclasses import dataclass

DEFAULT_RATE_LIMIT_WAIT = 60.0


@dataclass(frozen=True)
class Classification:
    error_type: str
    retryable: bool
    retry_after: float | None = None


def classify(status: int, headers: Mapping[str, str], body: str = "", now: float | None = None) -> Classification:
    """Classify a non-2xx GitHub response."""
    h = {k.lower(): v for k, v in headers.items()}
    if status >= 500:
        return Classification("GitHubServerError", True)
    rate_limited = status == 429 or (
        status == 403
        and ("retry-after" in h or h.get("x-ratelimit-remaining") == "0" or "secondary rate limit" in body.lower())
    )
    if rate_limited:
        return Classification("GitHubRateLimited", True, _wait_seconds(h, time.time() if now is None else now))
    if status in (401, 403):
        return Classification("GitHubAuthError", False)
    if status == 404:
        return Classification("GitHubNotFound", False)
    if status == 422:
        return Classification("GitHubUnprocessable", False)
    return Classification("GitHubClientError", False)


def _wait_seconds(headers: dict[str, str], now: float) -> float:
    try:
        if "retry-after" in headers:
            return max(1.0, float(headers["retry-after"]))
        if headers.get("x-ratelimit-remaining") == "0" and "x-ratelimit-reset" in headers:
            return max(1.0, float(headers["x-ratelimit-reset"]) - now)
    except ValueError:
        pass
    return DEFAULT_RATE_LIMIT_WAIT
