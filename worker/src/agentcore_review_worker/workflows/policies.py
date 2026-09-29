"""Activity timeouts and retry policies, shared by the workflows.

Every activity heartbeats every 5 s (activities/heartbeats.py) under a 10 s heartbeat timeout: an attempt cut off by
a killed session is retried after 10 s whatever its start-to-close, which can then fit the worst case of its calls.
"""

from datetime import timedelta
from typing import Any

from temporalio.common import RetryPolicy

HEARTBEAT_TIMEOUT = timedelta(seconds=10)

FIVE_ATTEMPTS = RetryPolicy(maximum_attempts=5)
THREE_ATTEMPTS = RetryPolicy(maximum_attempts=3)
SINGLE_ATTEMPT = RetryPolicy(maximum_attempts=1)

# A call cut off by a killed session is retried on a new one after a short backoff. The plugin's failure converter
# leaves throttling retryable, so the attempt cap bounds a persistent retryable Bedrock error: a killed session needs
# far fewer attempts, and a backoff of 1+2+4+8+15×15 s gives a throttling spike about 4 min before the agent becomes
# unavailable.
MODEL_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(seconds=15),
    maximum_attempts=20,
    # Bedrock error codes that fail the same way on every attempt (the model factory types errors by their code).
    non_retryable_error_types=[
        "ValidationException",
        "AccessDeniedException",
        "ResourceNotFoundException",
        "UnrecognizedClientException",
    ],
)


def _options(seconds: int, retry: RetryPolicy) -> dict[str, Any]:
    return {
        "start_to_close_timeout": timedelta(seconds=seconds),
        "heartbeat_timeout": HEARTBEAT_TIMEOUT,
        "retry_policy": retry,
    }


# Model calls: a start-to-close for the longest answer (MAX_TOKENS in agent_model.py). The plugin heartbeats every
# 5 s and the SDK sends one per 8 s at most: a 2 s margin. History replays completed calls, never re-billed.
MODEL_ACTIVITY = {**_options(600, MODEL_RETRY), "schedule_to_close_timeout": timedelta(minutes=15)}

# A GitHub call gives up after 10 s, inside its attempt; an attempt fits its sequential calls, plus 1 s between writes.
GITHUB_CALL = _options(30, FIVE_ATTEMPTS)  # up to two calls (a read may take pages)
# A tool call (the session's first one downloads and extracts the snapshot), ListFiles, RecoverCounters.
MULTI_CALL = _options(60, FIVE_ATTEMPTS)
# Up to a reply and a resolution per thread, a second apart: 10 minutes fit about 200 threads.
GITHUB_THREADS = _options(600, THREE_ATTEMPTS)
SLOW_TRANSFER = _options(120, FIVE_ATTEMPTS)  # a review with many inline comments, a repository archive
COMMIT_FIX = _options(180, THREE_ATTEMPTS)
DELETE_SNAPSHOTS = _options(30, SINGLE_ATTEMPT)  # never fatal: the S3 lifecycle rule is the safety net
PING = _options(30, THREE_ATTEMPTS)  # a broken worker must fail make ping, not hang it

# Children never retry: their activities do. A reviewer makes up to HARD_TURN_LIMIT (limits.py) model calls, often
# 60-80 s each, plus a recovery after a killed session, and outlasts one model call's schedule-to-close. A child that
# times out leaves its reviewer unavailable.
CHILD_RUN_TIMEOUT = timedelta(minutes=20)
