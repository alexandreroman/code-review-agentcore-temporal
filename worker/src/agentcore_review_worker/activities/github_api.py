"""The worker's GitHub access: the GitHub App client, request helpers, and GitHub errors as Temporal errors.

Installation tokens are cached in process memory by GitHubApp; no secret reaches the Temporal history.
Helpers raise GitHubError; each activity converts it at its boundary with github_errors(), so it can
still handle a specific status (a 404, a 422) itself.
"""

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import timedelta
from functools import cache
from typing import Any

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubApp, GitHubError
from agentcore_review_shared.secrets import GitHubAppSecret
from temporalio.exceptions import ApplicationError

from ..aws import read_secret

GITHUB_RAW = "application/vnd.github.raw+json"
PER_PAGE = 100
MAX_ITEMS = 3000
# A slow request fails inside its activity attempt, with time left to retry.
GITHUB_TIMEOUT_SECONDS = 10.0
WRITE_SPACING_SECONDS = 1.0  # content creation is capped at 80 per minute and 500 per hour

_secret_id: str | None = None
_write_lock = asyncio.Lock()
_last_write = 0.0

# --- client ---


def configure(secret_id: str) -> None:
    """Called once by build_worker, before any activity runs."""
    global _secret_id
    _secret_id = secret_id


@cache
def _secret() -> GitHubAppSecret:
    if _secret_id is None:
        raise RuntimeError("github_api.configure() was not called")
    return GitHubAppSecret.model_validate_json(read_secret(_secret_id))


@cache
def github() -> GitHubApp:
    """The process's GitHub App client, built on first use from Secrets Manager."""
    secret = _secret()
    return GitHubApp(secret.client_id, secret.private_key, timeout=GITHUB_TIMEOUT_SECONDS)


def bot_login() -> str:
    """The login on the app's own reviews and comments in the REST API: "<app slug>[bot]"."""
    return f"{_secret().slug}[bot]"


# --- request helpers ---


def repo_path(pr: PrRef) -> str:
    return f"/repos/{pr.owner}/{pr.repo}"


async def get(pr: PrRef, path: str, params: dict | None = None) -> Any:
    """The decoded JSON body."""
    response = await github().request(pr.installation_id, "GET", path, params=params)
    return response.json()


async def get_raw(pr: PrRef, path: str, params: dict | None = None) -> bytes:
    """The raw bytes of a file, from the contents API."""
    response = await github().request(pr.installation_id, "GET", path, params=params, accept=GITHUB_RAW)
    return response.content


async def get_pages(pr: PrRef, path: str, params: dict | None = None) -> list[dict]:
    items: list[dict] = []
    for page in range(1, MAX_ITEMS // PER_PAGE + 1):
        batch = await get(pr, path, {**(params or {}), "per_page": PER_PAGE, "page": page})
        items.extend(batch)
        if len(batch) < PER_PAGE:
            break
    return items


@asynccontextmanager
async def spaced_write() -> AsyncIterator[None]:
    """Serialize this process's GitHub writes, at least one second apart."""
    global _last_write
    async with _write_lock:
        delay = _last_write + WRITE_SPACING_SECONDS - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        try:
            yield
        finally:
            _last_write = time.monotonic()


async def send(pr: PrRef, method: str, path: str, body: dict) -> Any:
    async with spaced_write():
        response = await github().request(pr.installation_id, method, path, json=body)
    return response.json() if response.content else None


# --- the bot's own reviews and comments ---


def author_login(item: dict) -> str:
    """The login of a REST review's or comment's author."""
    return (item.get("user") or {}).get("login", "")


def body_of(item: dict) -> str:
    """The body of a REST review or comment: GitHub sends null for an empty one."""
    return item.get("body") or ""


def find_marked(items: list[dict], marker: str) -> dict | None:
    """The first of the bot's reviews or comments that carries the marker.

    Anyone else's is ignored: workflow IDs are guessable, so a participant could post a copy of a marker to
    suppress what the bot is about to write.
    """
    bot = bot_login()
    return next((item for item in items if author_login(item) == bot and marker in body_of(item)), None)


async def post_once(pr: PrRef, comments_path: str, post_path: str, body: str, marker: str) -> None:
    """Post a comment unless an earlier attempt already did: the bot's comments are searched for its marker."""
    comments = await get_pages(pr, comments_path)
    if find_marked(comments, marker) is None:
        await send(pr, "POST", post_path, {"body": body})


# --- error conversion ---


@contextmanager
def github_errors() -> Iterator[None]:
    """Wrap an activity body: a GitHubError leaves it as an ApplicationError, typed and retried as classified.

    Rate limits wait for Retry-After (or 60 s); 401, 403, 404 and 422 are never retried.
    """
    try:
        yield
    except GitHubError as error:
        classification = error.classification
        delay = timedelta(seconds=classification.retry_after) if classification.retry_after else None
        raise ApplicationError(
            str(error),
            type=classification.error_type,
            non_retryable=not classification.retryable,
            next_retry_delay=delay,
        ) from error
