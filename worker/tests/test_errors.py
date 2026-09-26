from datetime import timedelta

import pytest
from agentcore_review_shared.github import GitHubError
from agentcore_review_shared.github_errors import classify
from agentcore_review_worker.errors import github_application_error, github_errors
from temporalio.exceptions import ApplicationError


def error(status: int, headers: dict | None = None, body: str = "") -> GitHubError:
    return GitHubError(status, classify(status, headers or {}, body), body)


def test_unprocessable_is_final():
    converted = github_application_error(error(422, body="Line could not be resolved"))
    assert converted.type == "GitHubUnprocessable"
    assert converted.non_retryable and converted.next_retry_delay is None


def test_rate_limits_wait_for_retry_after():
    converted = github_application_error(error(403, {"Retry-After": "90"}))
    assert not converted.non_retryable
    assert converted.next_retry_delay == timedelta(seconds=90)


def test_server_errors_follow_the_retry_policy():
    converted = github_application_error(error(502))
    assert converted.type == "GitHubServerError"
    assert not converted.non_retryable and converted.next_retry_delay is None


def test_the_context_manager_converts_github_errors_only():
    with pytest.raises(ApplicationError) as caught, github_errors():
        raise error(404)
    assert caught.value.type == "GitHubNotFound"
    with pytest.raises(KeyError), github_errors():
        raise KeyError("other")
