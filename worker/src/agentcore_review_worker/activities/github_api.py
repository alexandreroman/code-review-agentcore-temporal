"""Thin helpers over the GitHub App client: paginated reads and spaced writes.

Helpers raise GitHubError; each activity converts it at its boundary with errors.github_errors(), so
it can still handle a specific status (a 404, a 422) itself.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from agentcore_review_shared.contract import PrRef

from ..github_client import github

PER_PAGE = 100
MAX_ITEMS = 3000
WRITE_SPACING_SECONDS = 1.0  # content creation is capped at 80 per minute and 500 per hour

_write_lock = asyncio.Lock()
_last_write = 0.0


def repo_path(pr: PrRef) -> str:
    return f"/repos/{pr.owner}/{pr.repo}"


async def get(pr: PrRef, path: str, params: dict | None = None) -> Any:
    response = await github().request(pr.installation_id, "GET", path, params=params)
    return response.json()


async def get_pages(pr: PrRef, path: str, params: dict | None = None, limit: int = MAX_ITEMS) -> list[dict]:
    items: list[dict] = []
    for page in range(1, limit // PER_PAGE + 1):
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
