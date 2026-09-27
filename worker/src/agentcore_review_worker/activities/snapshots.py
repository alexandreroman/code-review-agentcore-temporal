"""Repository snapshots in S3 (claim-check): one archive per reviewed SHA, shared by every agent of the round.

The parent workflow only sees the S3 key; the archive streams from GitHub to a temporary file and then
to S3, never held in memory.
"""

import asyncio
import tempfile
from collections.abc import Awaitable
from pathlib import Path

import httpx2 as httpx
from agentcore_review_shared.contract import PrRef
from agentcore_review_shared.github import API_URL, raise_for_status
from botocore.exceptions import ClientError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from ..aws import s3
from ..models import SnapshotInput, SnapshotRef
from ..settings import AppSettings
from .github_api import github, github_errors

MAX_ARCHIVE_BYTES = 200 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
HEARTBEAT_SECONDS = 5.0


def snapshot_prefix(owner: str, repo: str, number: int) -> str:
    return f"{owner.lower()}/{repo.lower()}/pr-{number}/"


def snapshot_key(owner: str, repo: str, number: int, sha: str) -> str:
    return f"{snapshot_prefix(owner, repo, number)}{sha}.tar.gz"


class SnapshotActivities:
    def __init__(self, settings: AppSettings) -> None:
        self._bucket = settings.snapshots_bucket

    @activity.defn(name="snapshot_repo")
    async def snapshot_repo(self, input: SnapshotInput) -> SnapshotRef:
        """Archive the repository at `sha` into S3; a no-op when the key already exists."""
        pr = input.pr
        key = snapshot_key(pr.owner, pr.repo, pr.number, input.sha)
        ref = SnapshotRef(
            owner=pr.owner,
            repo=pr.repo,
            installation_id=pr.installation_id,
            sha=input.sha,
            bucket=self._bucket,
            key=key,
        )
        if await asyncio.to_thread(_exists, self._bucket, key):
            return ref
        with tempfile.TemporaryDirectory() as work:
            archive = Path(work) / "archive.tar.gz"
            with github_errors():
                await _download_tarball(pr, input.sha, archive)
            await _heartbeating(asyncio.to_thread(s3().upload_file, str(archive), self._bucket, key))
        return ref

    @activity.defn(name="delete_snapshots")
    async def delete_snapshots(self, pr: PrRef) -> int:
        """Delete every snapshot of the pull request; deleting nothing is not an error."""
        return await asyncio.to_thread(_delete_prefix, self._bucket, snapshot_prefix(pr.owner, pr.repo, pr.number))


def _exists(bucket: str, key: str) -> bool:
    try:
        s3().head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
            return False
        raise
    return True


async def _download_tarball(pr: PrRef, sha: str, archive: Path) -> None:
    token = await github().installation_token(pr.installation_id)
    url = f"{API_URL}/repos/{pr.owner}/{pr.repo}/tarball/{sha}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    # GitHub redirects to codeload with a short-lived token in the URL, also for a private repository.
    async with (
        httpx.AsyncClient(timeout=60.0, follow_redirects=True) as http,
        http.stream("GET", url, headers=headers) as response,
    ):
        if not response.is_success:
            await response.aread()
            raise_for_status(response)
        size = 0
        with archive.open("wb") as out:
            async for chunk in response.aiter_bytes(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_ARCHIVE_BYTES:
                    raise ApplicationError(
                        f"repository archive larger than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB",
                        type="SnapshotTooLarge",
                        non_retryable=True,
                    )
                out.write(chunk)
                activity.heartbeat(size)


async def _heartbeating[T](work: Awaitable[T]) -> T:
    """Await `work` while heartbeating: an upload over a slow uplink outlasts the 15 s heartbeat timeout."""
    task = asyncio.ensure_future(work)
    while True:
        done, _ = await asyncio.wait({task}, timeout=HEARTBEAT_SECONDS)
        if done:
            return task.result()
        activity.heartbeat("uploading")


def _delete_prefix(bucket: str, prefix: str) -> int:
    deleted = 0
    for page in s3().get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        objects = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        if objects:
            s3().delete_objects(Bucket=bucket, Delete={"Objects": objects, "Quiet": True})
            deleted += len(objects)
    return deleted
