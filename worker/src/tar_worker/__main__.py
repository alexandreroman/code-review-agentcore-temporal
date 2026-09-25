"""Starter entry point of the worker: `python -m tar_worker`."""

import logging
import os

logger = logging.getLogger(__name__)


def main() -> None:
    """Log the Temporal settings the worker will use, then exit."""
    logging.basicConfig(level=logging.INFO)
    namespace = os.environ.get("TEMPORAL_NAMESPACE")
    task_queue = os.environ.get("DEV_TASK_QUEUE", "review-dev")
    logger.info(
        "tar-worker starter: namespace=%s task_queue=%s; the Temporal worker itself is implemented in plan 3",
        namespace,
        task_queue,
    )


if __name__ == "__main__":
    main()
