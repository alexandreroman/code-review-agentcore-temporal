"""Local cache of repository snapshots: /tmp/snapshots/{sha}/, filled from S3 on first read.

S3 is the source of truth and this cache lives as long as the AgentCore session: a session started
after /kill downloads the archive again from S3, without calling GitHub. A lock per SHA makes the
parallel tool calls of a session wait for a single download and extraction.
"""

import asyncio
import shutil
import tarfile
import tempfile
from pathlib import Path

from ..aws import s3
from ..models import SnapshotRef

CACHE_ROOT = Path("/tmp/snapshots")
_locks: dict[str, asyncio.Lock] = {}


async def local_root(snapshot: SnapshotRef) -> Path:
    target = CACHE_ROOT / snapshot.sha
    if target.is_dir():
        return target
    async with _locks.setdefault(snapshot.sha, asyncio.Lock()):
        if not target.is_dir():
            await asyncio.to_thread(_fetch, snapshot.bucket, snapshot.key, target)
    return target


def _fetch(bucket: str, key: str, target: Path) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{target.name}-", dir=CACHE_ROOT))
    try:
        archive = work / "archive.tar.gz"
        s3().download_file(bucket, key, str(archive))
        extract(archive, work / "repo")
        (work / "repo").rename(target)  # atomic: a reader sees the whole tree or nothing
    finally:
        shutil.rmtree(work, ignore_errors=True)


def extract(archive: Path, destination: Path) -> None:
    """Extract a GitHub tarball without its top-level "{owner}-{repo}-{sha}/" directory."""
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(destination, filter=_strip_top_level)


def _strip_top_level(member: tarfile.TarInfo, destination: str) -> tarfile.TarInfo | None:
    _, _, rest = member.name.partition("/")
    if not rest:
        return None
    changes = {"name": rest}
    if member.islnk():
        changes["linkname"] = member.linkname.partition("/")[2]
    try:
        return tarfile.data_filter(member.replace(**changes, deep=False), destination)
    except tarfile.FilterError:
        return None  # e.g. a link pointing outside the repository: skipped, never followed
