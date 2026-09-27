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
from typing import Any

from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import GitHubApp, GitHubError
from agentcore_review_shared.secrets import GitHubAppSecret
from temporalio.exceptions import ApplicationError

from ..aws import read_secret
from ..models import SnapshotRef

JSON = "application/vnd.github+json"
PER_PAGE = 100
MAX_ITEMS = 3000
WRITE_SPACING_SECONDS = 1.0  # content creation is capped at 80 per minute and 500 per hour

_secret_id: str | None = None
_app: GitHubApp | None = None
_slug: str | None = None
_write_lock = asyncio.Lock()
_last_write = 0.0

# --- client ---


def configure(secret_id: str) -> None:
    """Called once when the worker registers its activities."""
    global _secret_id
    _secret_id = secret_id


def github() -> GitHubApp:
    """The process's GitHub App client, built on first use from Secrets Manager."""
    global _app, _slug
    if _app is None:
        if _secret_id is None:
            raise RuntimeError("github_api.configure() was not called")
        secret = GitHubAppSecret.model_validate_json(read_secret(_secret_id))
        _app = GitHubApp(secret.client_id, secret.private_key)
        _slug = secret.slug
    return _app


def bot_login() -> str:
    """The login on the app's own comments: "<app slug>[bot]"."""
    github()  # reads the secret on first use
    return f"{_slug}[bot]"


# --- request helpers ---


def repo_path(ref: PrRef | SnapshotRef) -> str:
    return f"/repos/{ref.owner}/{ref.repo}"


async def get(ref: PrRef | SnapshotRef, path: str, params: dict | None = None, *, accept: str = JSON) -> Any:
    """The decoded JSON body, or the raw bytes when another media type is accepted."""
    response = await github().request(ref.installation_id, "GET", path, params=params, accept=accept)
    return response.json() if accept == JSON else response.content


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


# --- error conversion ---


def github_application_error(error: GitHubError) -> ApplicationError:
    """A GitHubError as an ApplicationError, typed and retried as the shared classifier says.

    Rate limits wait for Retry-After (or 60 s); 401, 403, 404 and 422 are never retried.
    """
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
