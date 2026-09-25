"""Which changed files get reviewed, and how they are split into reviewer batches."""

from fnmatch import fnmatch
from pathlib import PurePosixPath

from tar_worker.models import ChangedFile

EXCLUDED_NAME_PATTERNS = ("*.lock", "uv.lock", "package-lock.json", "*.min.js")
MAX_BATCH_FILES = 15
MAX_BATCH_PATCH_BYTES = 60_000


def is_excluded(changed: ChangedFile) -> bool:
    if changed.patch_bytes is None:
        return True
    name = PurePosixPath(changed.path).name
    return any(fnmatch(name, pattern) for pattern in EXCLUDED_NAME_PATTERNS)


def partition(files: list[ChangedFile]) -> tuple[list[ChangedFile], list[ChangedFile]]:
    reviewed = [f for f in files if not is_excluded(f)]
    excluded = [f for f in files if is_excluded(f)]
    return reviewed, excluded


def make_batches(
    files: list[ChangedFile], max_files: int = MAX_BATCH_FILES, max_bytes: int = MAX_BATCH_PATCH_BYTES
) -> list[list[ChangedFile]]:
    batches: list[list[ChangedFile]] = []
    current: list[ChangedFile] = []
    size = 0
    for f in files:
        patch = f.patch_bytes or 0
        if current and (len(current) >= max_files or size + patch > max_bytes):
            batches.append(current)
            current, size = [], 0
        current.append(f)
        size += patch
    if current:
        batches.append(current)
    return batches
