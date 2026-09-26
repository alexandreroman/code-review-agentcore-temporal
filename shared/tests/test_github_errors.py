import pytest
from agentic_review_shared.github_errors import DEFAULT_RATE_LIMIT_WAIT, classify


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retryable(status):
    c = classify(status, {})
    assert c.retryable and c.error_type == "GitHubServerError"


def test_429_uses_retry_after():
    c = classify(429, {"Retry-After": "12"})
    assert c.retryable and c.error_type == "GitHubRateLimited" and c.retry_after == 12.0


def test_primary_rate_limit_waits_until_reset():
    c = classify(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1030"}, now=1000.0)
    assert c.retryable and c.retry_after == 30.0


def test_secondary_rate_limit_without_headers_waits_default():
    c = classify(403, {}, body='{"message": "You have exceeded a secondary rate limit"}')
    assert c.retryable and c.retry_after == DEFAULT_RATE_LIMIT_WAIT


def test_retry_after_is_at_least_one_second():
    assert classify(429, {"retry-after": "0"}).retry_after == 1.0


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, "GitHubAuthError"),
        (403, "GitHubAuthError"),
        (404, "GitHubNotFound"),
        (422, "GitHubUnprocessable"),
        (409, "GitHubClientError"),
    ],
)
def test_client_errors_are_not_retryable(status, error_type):
    c = classify(status, {})
    assert not c.retryable and c.error_type == error_type and c.retry_after is None
