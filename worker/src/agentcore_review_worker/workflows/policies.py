"""Activity timeouts and retry policies, shared by the workflows."""

from datetime import timedelta
from typing import Any

from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

FIVE_ATTEMPTS = RetryPolicy(maximum_attempts=5)
THREE_ATTEMPTS = RetryPolicy(maximum_attempts=3)
SINGLE_ATTEMPT = RetryPolicy(maximum_attempts=1)

# A call cut off by a killed session is retried on a new one: a short backoff keeps the review from stalling.
# MODEL_ACTIVITY's 6 min schedule-to-close is the real bound: ten attempts lost to killed sessions cost at most
# 10 x (10 s heartbeat + 5 s backoff) = 150 s.
MODEL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=5),
    maximum_attempts=10,
    # Bedrock error codes that fail the same way on every attempt (the model factory types errors by their code).
    non_retryable_error_types=[
        "ValidationException",
        "AccessDeniedException",
        "ResourceNotFoundException",
        "UnrecognizedClientException",
    ],
)


def _options(seconds: int, retry: RetryPolicy, heartbeat: int | None = None) -> dict[str, Any]:
    options: dict[str, Any] = {"start_to_close_timeout": timedelta(seconds=seconds), "retry_policy": retry}
    if heartbeat is not None:
        options["heartbeat_timeout"] = timedelta(seconds=heartbeat)
    return options


# Model calls: a 10 s heartbeat detects a killed session fast; history replays completed calls, never re-billed.
# The plugin heartbeats every 5 s (half the timeout) and the SDK sends one per 8 s at most: a 2 s margin.
MODEL_ACTIVITY = {**_options(180, MODEL_RETRY, heartbeat=10), "schedule_to_close_timeout": timedelta(minutes=6)}
# A session's first tool call downloads and extracts the snapshot. The tools heartbeat every 5 s while they run:
# a call cut off by a killed session is retried after 10 s, not 60.
TOOL_ACTIVITY = _options(60, FIVE_ATTEMPTS, heartbeat=10)

SNAPSHOT = _options(120, FIVE_ATTEMPTS, heartbeat=10)

# A GitHub call gives up after 10 s: a slow one fails inside its attempt (typed, retried) instead of running on
# while Temporal starts the next one. An attempt must fit its sequential calls, plus 1 s between writes.
# These make many calls and heartbeat every 5 s while they run: a start-to-close sized for the worst case costs
# nothing when a killed session cuts one off, retried after 10 s.
LIST_FILES = _options(60, FIVE_ATTEMPTS, heartbeat=10)
PUBLISH_REVIEW = _options(120, FIVE_ATTEMPTS, heartbeat=10)  # a review with many inline comments is slow to post
RECOVER_COUNTERS = _options(60, FIVE_ATTEMPTS, heartbeat=10)  # reads only: the run's first review waits for it
# Up to a reply and a resolution per thread, a second apart: 10 minutes fit about 200 threads.
RESOLVE_THREADS = _options(600, THREE_ATTEMPTS, heartbeat=10)
CLOSE_EARLIER_THREADS = _options(600, THREE_ATTEMPTS, heartbeat=10)
COMMIT_FIX = _options(180, THREE_ATTEMPTS, heartbeat=10)
# These make up to two calls (a read may take pages).
FETCH_DIFF = _options(30, FIVE_ATTEMPTS)
UPDATE_CHECK = _options(30, FIVE_ATTEMPTS)
READ_THREAD = _options(30, FIVE_ATTEMPTS)
REPLY_IN_THREAD = _options(30, FIVE_ATTEMPTS)
POST_COMMENT = _options(30, FIVE_ATTEMPTS)
CLOSE_PR = _options(30, FIVE_ATTEMPTS)
DELETE_SNAPSHOTS = _options(30, SINGLE_ATTEMPT)  # never fatal: the S3 lifecycle rule is the safety net
PING = _options(30, THREE_ATTEMPTS)  # a broken worker must fail make ping, not hang it

# Children never retry: their activities do. A reviewer makes up to HARD_TURN_LIMIT (limits.py) model calls, often
# 60-80 s each, plus a recovery after a killed session: a child that times out leaves its reviewer unavailable.
CHILD_RUN_TIMEOUT = timedelta(minutes=20)


def error_type(error: BaseException) -> str | None:
    """The type of the first ApplicationError behind a failure: GitHubUnprocessable, or BranchMoved behind a child's."""
    cause = error.__cause__
    while cause is not None and not isinstance(cause, ApplicationError):
        cause = cause.__cause__
    return cause.type if cause is not None else None
