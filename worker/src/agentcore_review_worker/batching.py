"""Which changed files get reviewed, and how they are split into reviewer batches."""

from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from agentcore_review_worker.models import ChangedFile

EXCLUDED_NAME_PATTERNS = ("*.lock", "package-lock.json", "*.min.js")
MAX_BATCH_FILES = 15
MAX_BATCH_PATCH_BYTES = 60_000


def is_excluded(changed: ChangedFile) -> bool:
    if changed.patch_bytes is None:
        return True
    name = PurePosixPath(changed.path).name
    # fnmatchcase: case-sensitive on every OS.
    return any(fnmatchcase(name, pattern) for pattern in EXCLUDED_NAME_PATTERNS)


def partition(files: list[ChangedFile]) -> tuple[list[ChangedFile], list[ChangedFile]]:
    """The reviewed files and the excluded ones, each in the given order."""
    reviewed: list[ChangedFile] = []
    excluded: list[ChangedFile] = []
    for f in files:
        if is_excluded(f):
            excluded.append(f)
        else:
            reviewed.append(f)
    return reviewed, excluded


def make_batches(files: list[ChangedFile]) -> list[list[ChangedFile]]:
    batches: list[list[ChangedFile]] = []
    current: list[ChangedFile] = []
    size = 0
    for f in files:
        patch = f.patch_bytes or 0
        if current and (len(current) >= MAX_BATCH_FILES or size + patch > MAX_BATCH_PATCH_BYTES):
            batches.append(current)
            current, size = [], 0
        current.append(f)
        size += patch
    if current:
        batches.append(current)
    return batches
