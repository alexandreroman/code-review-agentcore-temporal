"""Glob, Grep and Read: the agents' navigation tools, run as activities named like Claude Code's tools.

Workflow modules import this module through the sandbox passthrough, to wrap these functions with
activity_as_tool. Beyond 200 MB there is no snapshot (key None): Glob reads the git tree, Read the
contents API, and Grep is unavailable.
"""

import asyncio
from pathlib import PurePosixPath
from urllib.parse import quote

from agentcore_review_shared.github import GitHubError
from temporalio import activity

from ..models import SnapshotRef
from ..navigation import glob_files, glob_paths, grep_files, read_file, render_file
from .github_api import get, github_errors, repo_path
from .snapshot_cache import local_root

GREP_UNAVAILABLE = (
    "Error: Grep is unavailable for this pull request: the repository is too large for a local snapshot. "
    "Use Glob and Read instead."
)


@activity.defn(name="Glob")
async def glob_tool(snapshot: SnapshotRef, pattern: str, path: str | None = None) -> str:
    """Find files by glob pattern.

    Returns the matching paths, relative to the repository root and sorted (at most 500).

    Args:
        pattern: Glob pattern, e.g. "app/**/*.py"; "**" matches any number of directories.
        path: Directory to search from, relative to the repository root (default: the root).
    """
    if snapshot.key is None:
        return glob_paths(await _tree_paths(snapshot), pattern, path)
    return await asyncio.to_thread(glob_files, await local_root(snapshot), pattern, path)


@activity.defn(name="Grep")
async def grep_tool(snapshot: SnapshotRef, pattern: str, path: str | None = None, glob: str | None = None) -> str:
    """Search file contents with a regular expression. Returns at most 50 matches as "path:line: text".

    Args:
        pattern: Regular expression (Python syntax) searched in each line.
        path: File or directory to search, relative to the repository root (default: the root).
        glob: Only search files matching this glob pattern, e.g. "*.py".
    """
    if snapshot.key is None:
        return GREP_UNAVAILABLE
    return await asyncio.to_thread(grep_files, await local_root(snapshot), pattern, path, glob)


@activity.defn(name="Read")
async def read_tool(
    snapshot: SnapshotRef, file_path: str, offset: int | str | None = None, limit: int | str | None = None
) -> str:
    """Read a file with line numbers, at most 400 lines or 40 KB at a time.

    Args:
        file_path: Path relative to the repository root, e.g. "app/main.py".
        offset: First line to read, starting at 1 (default: 1).
        limit: Number of lines to read (default and maximum: 400).
    """
    if snapshot.key is not None:
        return await asyncio.to_thread(read_file, await local_root(snapshot), file_path, offset, limit)
    if file_path.startswith("/") or ".." in PurePosixPath(file_path).parts:
        return f"Error: path {file_path!r} is outside the repository."
    with github_errors():
        data = await _contents(snapshot, file_path)
    return f"Error: file {file_path!r} not found." if data is None else render_file(file_path, data, offset, limit)


async def _tree_paths(snapshot: SnapshotRef) -> list[str]:
    with github_errors():
        tree = await get(snapshot, f"{repo_path(snapshot)}/git/trees/{snapshot.sha}", {"recursive": "1"})
    return [entry["path"] for entry in tree["tree"] if entry["type"] == "blob"]


async def _contents(snapshot: SnapshotRef, file_path: str) -> bytes | None:
    """The file's raw bytes at the snapshot's SHA, or None when it does not exist."""
    try:
        return await get(
            snapshot,
            f"{repo_path(snapshot)}/contents/{quote(file_path.strip('/'))}",
            {"ref": snapshot.sha},
            accept="application/vnd.github.raw+json",
        )
    except GitHubError as error:
        if error.status == 404:
            return None
        raise
