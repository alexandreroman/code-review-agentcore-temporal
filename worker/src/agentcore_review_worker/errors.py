"""GitHub errors as Temporal ApplicationErrors: type and retryability come from the shared classifier."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from agentcore_review_shared.github import GitHubError
from temporalio.exceptions import ApplicationError


def github_application_error(error: GitHubError) -> ApplicationError:
    """Rate limits wait for Retry-After (or 60 s); 401, 403, 404 and 422 are never retried."""
    classification = error.classification
    delay = timedelta(seconds=classification.retry_after) if classification.retry_after else None
    return ApplicationError(
        str(error), type=classification.error_type, non_retryable=not classification.retryable, next_retry_delay=delay
    )


@contextmanager
def github_errors() -> Iterator[None]:
    """Wrap an activity body: a GitHubError leaves it as a typed ApplicationError."""
    try:
        yield
    except GitHubError as error:
        raise github_application_error(error) from error
