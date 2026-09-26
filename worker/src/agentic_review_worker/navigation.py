"""Glob, Grep and Read over a local repository snapshot, bounded and confined to the snapshot.

These functions return text meant for the agent: invalid input produces an "Error: ..." message
instead of an exception, so a bad tool call never fails the activity.
"""

import re
from pathlib import Path, PurePosixPath

MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 50
MAX_READ_LINES = 400
MAX_READ_BYTES = 40_000
MAX_GREP_LINE_CHARS = 300
MAX_READ_LINE_CHARS = 2_000
_BINARY_SNIFF_BYTES = 8_192


class _OutsideRepository(ValueError):
    pass


class _InvalidArgument(ValueError):
    pass


def _coerce_int(value: object, name: str) -> int | None:
    """Coerce an offset/limit argument to an int, or None if it was not given.

    Accepts int, None, or a string holding a base-10 integer (an LLM may quote a
    numeral). Anything else — including bool and float — is invalid.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise _InvalidArgument(f"{name} must be an integer, got {value!r}.")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise _InvalidArgument(f"{name} must be an integer, got {value!r}.") from None
    raise _InvalidArgument(f"{name} must be an integer, got {value!r}.")


def _resolve(root: Path, relative: str | None) -> Path:
    base = root.resolve()
    target = (base / (relative or ".")).resolve()
    if target != base and base not in target.parents:
        raise _OutsideRepository(relative)
    return target


def _inside(root: Path, candidate: Path) -> bool:
    resolved = candidate.resolve()
    return resolved == root or root in resolved.parents


def _read_text(path: Path) -> str | None:
    data = path.read_bytes()
    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        return None
    return data.decode("utf-8", errors="replace")


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def glob_files(root: Path, pattern: str, path: str | None = None) -> str:
    base_root = root.resolve()
    try:
        base = _resolve(root, path)
        candidates = list(base.glob(pattern))
    except _OutsideRepository:
        return f"Error: path {path!r} is outside the repository."
    except (ValueError, NotImplementedError) as exc:
        return f"Error: invalid glob pattern {pattern!r}: {exc}"
    matches = sorted(str(p.relative_to(base_root)) for p in candidates if p.is_file() and _inside(base_root, p))
    if not matches:
        return "No files found."
    shown = matches[:MAX_GLOB_RESULTS]
    if len(matches) > len(shown):
        shown.append(f"... truncated: {len(matches) - MAX_GLOB_RESULTS} more files")
    return "\n".join(shown)


def _matches_glob(relative: PurePosixPath, glob: str) -> bool:
    """Match a relative path the way Glob does, including "**" segments.

    PurePosixPath.match treats "**" like "*" and anchors on the right, so it
    misses top-level files and over-restricts patterns like "app/**/*.py".
    full_match does not have that problem, but as a safety net we also try
    the pattern with a leading "**/" removed, which allows zero directories.
    """
    if "/" not in glob:
        return PurePosixPath(relative.name).full_match(glob)
    if relative.full_match(glob):
        return True
    trimmed = glob.removeprefix("**/")
    return trimmed != glob and relative.full_match(trimmed)


def grep_files(root: Path, pattern: str, path: str | None = None, glob: str | None = None) -> str:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        return f"Error: invalid regular expression {pattern!r}: {exc}"
    base_root = root.resolve()
    try:
        base = _resolve(root, path)
    except _OutsideRepository:
        return f"Error: path {path!r} is outside the repository."
    candidates = [base] if base.is_file() else sorted(base.rglob("*"))
    hits: list[str] = []
    total = 0
    for candidate in candidates:
        if not candidate.is_file() or not _inside(base_root, candidate):
            continue
        relative = candidate.relative_to(base_root)
        if glob and not _matches_glob(PurePosixPath(relative.as_posix()), glob):
            continue
        text = _read_text(candidate)
        if text is None:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                total += 1
                if len(hits) < MAX_GREP_RESULTS:
                    hits.append(f"{relative.as_posix()}:{number}: {_clip(line.strip(), MAX_GREP_LINE_CHARS)}")
    if not hits:
        return "No matches found."
    if total > len(hits):
        hits.append(f"... truncated: {total - len(hits)} more matches")
    return "\n".join(hits)


def read_file(root: Path, file_path: str, offset: int | str | None = None, limit: int | str | None = None) -> str:
    try:
        offset = _coerce_int(offset, "offset")
        limit = _coerce_int(limit, "limit")
    except _InvalidArgument as exc:
        return f"Error: {exc}"
    try:
        target = _resolve(root, file_path)
    except _OutsideRepository:
        return f"Error: path {file_path!r} is outside the repository."
    if not target.is_file():
        return f"Error: file {file_path!r} not found."
    text = _read_text(target)
    if text is None:
        return f"Error: {file_path!r} is a binary file."
    lines = text.splitlines()
    if not lines:
        return "(empty file)"
    start = max(1, offset or 1)
    if start > len(lines):
        return f"Error: offset {start} is beyond the end of {file_path!r} ({len(lines)} lines)."
    requested = min(limit or MAX_READ_LINES, MAX_READ_LINES)
    window: list[str] = []
    size = 0
    for number in range(start, min(len(lines), start + requested - 1) + 1):
        rendered = f"{number:6d}\t{_clip(lines[number - 1], MAX_READ_LINE_CHARS)}"
        if window and size + len(rendered.encode()) + 1 > MAX_READ_BYTES:
            break
        window.append(rendered)
        size += len(rendered.encode()) + 1
    end = start + len(window) - 1
    if start == 1 and end == len(lines):
        return "\n".join(window)
    header = (
        f"[{file_path}: {len(lines)} lines, {target.stat().st_size} bytes; showing lines {start}-{end}. "
        "Use offset and limit to read other ranges.]"
    )
    return "\n".join([header, *window])
