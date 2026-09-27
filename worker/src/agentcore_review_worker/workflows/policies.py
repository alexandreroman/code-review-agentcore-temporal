"""Activity timeouts and retry policies, shared by the workflows."""

from datetime import timedelta
from typing import Any

from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

FIVE_ATTEMPTS = RetryPolicy(maximum_attempts=5)
THREE_ATTEMPTS = RetryPolicy(maximum_attempts=3)
SINGLE_ATTEMPT = RetryPolicy(maximum_attempts=1)

MODEL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=60),
    maximum_attempts=5,
    # Anthropic SDK exception class names: the Strands plugin keeps them as the error type.
    non_retryable_error_types=["BadRequestError", "AuthenticationError", "PermissionDeniedError", "NotFoundError"],
)


def _options(seconds: int, retry: RetryPolicy, heartbeat: int | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {"start_to_close_timeout": timedelta(seconds=seconds), "retry_policy": retry}
    if heartbeat is not None:
        options["heartbeat_timeout"] = timedelta(seconds=heartbeat)
    return options


# Model calls: a 15 s heartbeat detects a killed session fast; history replays completed calls, never re-billed.
MODEL_ACTIVITY = {**_options(180, MODEL_RETRY, heartbeat=15), "schedule_to_close_timeout": timedelta(minutes=6)}
# A session's first tool call downloads and extracts the snapshot.
TOOL_ACTIVITY = _options(60, FIVE_ATTEMPTS)

LIST_CHANGED_FILES = _options(30, FIVE_ATTEMPTS)
SNAPSHOT_REPO = _options(120, FIVE_ATTEMPTS, heartbeat=15)
FETCH_BATCH_PATCHES = _options(30, FIVE_ATTEMPTS)
SET_CHECK = _options(15, FIVE_ATTEMPTS)
PUBLISH_REVIEW = _options(30, FIVE_ATTEMPTS)
RESOLVE_THREADS = _options(30, THREE_ATTEMPTS)
READ_THREAD = _options(15, FIVE_ATTEMPTS)
POST_THREAD_REPLY = _options(15, FIVE_ATTEMPTS)
POST_CLOSING_COMMENT = _options(15, FIVE_ATTEMPTS)
COMMIT_CHANGES = _options(60, THREE_ATTEMPTS)
DELETE_SNAPSHOTS = _options(30, SINGLE_ATTEMPT)  # never fatal: the S3 lifecycle rule is the safety net

# Children never retry: their activities do.
CHILD_RUN_TIMEOUT = timedelta(minutes=10)


def failed_with(error: ActivityError, error_type: str) -> bool:
    """Whether an activity failed with an ApplicationError of this type (e.g. GitHubUnprocessable)."""
    return isinstance(error.cause, ApplicationError) and error.cause.type == error_type
