"""Glob, Grep and Read over a local repository snapshot, bounded and confined to the snapshot.

These functions return text meant for the agent: invalid input produces an "Error: ..." message
instead of an exception, so a bad tool call never fails the activity. Every read is bounded in
size and every search in time, so a tool call always answers well within its activity timeout.
"""

import time
from pathlib import Path, PurePosixPath

import regex

MAX_GLOB_RESULTS = 500
MAX_GREP_RESULTS = 50
MAX_READ_LINES = 400
MAX_READ_BYTES = 40_000
MAX_GREP_LINE_CHARS = 300
MAX_READ_LINE_CHARS = 2_000
MAX_FILE_BYTES = 2_000_000
GREP_TIME_BUDGET = 10.0
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
    text = relative or "."
    # A lone surrogate (e.g. from malformed agent input) cannot round-trip
    # through the filesystem; fail here with a plain ValueError rather than
    # deeper inside path resolution, where a NUL byte also raises ValueError.
    text.encode()
    target = (base / text).resolve()
    if target != base and base not in target.parents:
        raise _OutsideRepository(relative)
    return target


def _inside(root: Path, candidate: Path) -> bool:
    resolved = candidate.resolve()
    return resolved == root or root in resolved.parents


def _read_text(path: Path) -> str | None:
    """The file as text, or None for a binary file; the binary test reads only the first bytes."""
    with path.open("rb") as handle:
        head = handle.read(_BINARY_SNIFF_BYTES)
        if b"\x00" in head:
            return None
        data = head + handle.read()
    return data.decode("utf-8", errors="replace")


def _git_lines(text: str) -> list[str]:
    """Split text into lines the way git does: on "\\n" only.

    str.splitlines() also breaks on "\\x0c", "\\v", "\\x1c"-"\\x1e", "\\x85" and
    a lone "\\r", which would miscount lines relative to GitHub. A trailing
    "\\r" (CRLF) is stripped from each line, and the empty element produced by
    a trailing newline is dropped.
    """
    split = text.split("\n")
    if split and split[-1] == "":
        split.pop()
    return [line.removesuffix("\r") for line in split]


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _glob_output(matches: list[str]) -> str:
    if not matches:
        return "No files found."
    shown = matches[:MAX_GLOB_RESULTS]
    if len(matches) > len(shown):
        shown.append(f"... truncated: {len(matches) - MAX_GLOB_RESULTS} more files")
    return "\n".join(shown)


def glob_files(root: Path, pattern: str, path: str | None = None) -> str:
    base_root = root.resolve()
    try:
        base = _resolve(root, path)
    except _OutsideRepository:
        return f"Error: path {path!r} is outside the repository."
    except ValueError as exc:
        return f"Error: invalid path {path!r}: {exc}"
    if not base.exists():
        return f"Error: path {path!r} not found."
    if not base.is_dir():
        return f"Error: path {path!r} is not a directory."
    try:
        candidates = list(base.glob(pattern))
    except (ValueError, NotImplementedError) as exc:
        return f"Error: invalid glob pattern {pattern!r}: {exc}"
    return _glob_output(
        sorted(str(p.relative_to(base_root)) for p in candidates if p.is_file() and _inside(base_root, p))
    )


def _validate_glob_pattern(pattern: str) -> None:
    """Raise the error Path.glob raises for a malformed pattern, without touching the filesystem.

    Path.glob validates its pattern as soon as it is called, before any directory is read, so
    calling it on a path that need not exist reproduces glob_files' errors (e.g. an empty or an
    absolute pattern) for glob_paths, which has no directory to glob against.
    """
    Path(".").glob(pattern)


def glob_paths(paths: list[str], pattern: str, path: str | None = None) -> str:
    """Glob over a list of repository paths (the GitHub tree fallback), answering like glob_files."""
    raw = path or ""
    if raw.startswith("/") or ".." in PurePosixPath(raw).parts:
        return f"Error: path {path!r} is outside the repository."
    if raw and raw in paths:
        return f"Error: path {path!r} is not a directory."
    base = PurePosixPath(raw)
    at_root = base == PurePosixPath(".")
    inside = [p for p in map(PurePosixPath, paths) if at_root or base in p.parents]
    if not inside and not at_root:
        return f"Error: path {path!r} not found."
    try:
        _validate_glob_pattern(pattern)
    except (ValueError, NotImplementedError) as exc:
        return f"Error: invalid glob pattern {pattern!r}: {exc}"
    matches = sorted(str(p) for p in inside if (p if at_root else p.relative_to(base)).full_match(pattern))
    return _glob_output(matches)


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


def grep_files(
    root: Path, pattern: str, path: str | None = None, glob: str | None = None, time_budget: float = GREP_TIME_BUDGET
) -> str:
    try:
        compiled = regex.compile(pattern)
    except (regex.error, ValueError) as exc:
        return f"Error: invalid regular expression {pattern!r}: {exc}"
    base_root = root.resolve()
    try:
        base = _resolve(root, path)
    except _OutsideRepository:
        return f"Error: path {path!r} is outside the repository."
    except ValueError as exc:
        return f"Error: invalid path {path!r}: {exc}"
    if not base.exists():
        return f"Error: path {path!r} not found."
    candidates = [base] if base.is_file() else sorted(base.rglob("*"))
    deadline = time.monotonic() + time_budget
    hits: list[str] = []
    total = too_large = 0
    stopped = False
    for candidate in candidates:
        if not candidate.is_file() or not _inside(base_root, candidate):
            continue
        relative = candidate.relative_to(base_root)
        if glob and not _matches_glob(PurePosixPath(relative.as_posix()), glob):
            continue
        if candidate.stat().st_size > MAX_FILE_BYTES:
            too_large += 1
            continue
        text = _read_text(candidate)
        if text is None:
            continue
        for number, line in enumerate(_git_lines(text), start=1):
            remaining = deadline - time.monotonic()
            try:
                if remaining <= 0:
                    raise TimeoutError
                # concurrent=True releases the GIL, so the activity keeps heartbeating meanwhile.
                found = compiled.search(line, timeout=remaining, concurrent=True)
            except TimeoutError:
                stopped = True
                break
            if found:
                total += 1
                if len(hits) < MAX_GREP_RESULTS:
                    hits.append(f"{relative.as_posix()}:{number}: {_clip(line.strip(), MAX_GREP_LINE_CHARS)}")
        if stopped:
            break
    notes = []
    if total > len(hits):
        notes.append(f"... truncated: {total - len(hits)} more matches")
    if too_large:
        notes.append(f"... skipped {too_large} files larger than {MAX_FILE_BYTES} bytes")
    if stopped:
        notes.append(
            f"... search stopped after {time_budget:g} s: narrow the path or glob, or simplify the regular expression"
        )
    return "\n".join([*(hits or ["No matches found."]), *notes])


def read_file(root: Path, file_path: str, offset: int | str | None = None, limit: int | str | None = None) -> str:
    try:
        target = _resolve(root, file_path)
    except _OutsideRepository:
        return f"Error: path {file_path!r} is outside the repository."
    except ValueError as exc:
        return f"Error: invalid path {file_path!r}: {exc}"
    if target.is_dir():
        return f"Error: {file_path!r} is a directory: use Glob to list its files."
    if not target.is_file():
        return f"Error: file {file_path!r} not found."
    size = target.stat().st_size
    if size > MAX_FILE_BYTES:
        return f"Error: {file_path!r} is too large to read ({size} bytes; limit {MAX_FILE_BYTES})."
    return render_file(file_path, target.read_bytes(), offset, limit)


def render_file(file_path: str, data: bytes, offset: int | str | None = None, limit: int | str | None = None) -> str:
    """A window of a file's lines for the agent; shared by the snapshot and the GitHub API fallback."""
    try:
        offset = _coerce_int(offset, "offset")
        limit = _coerce_int(limit, "limit")
    except _InvalidArgument as exc:
        return f"Error: {exc}"
    if limit is not None and limit < 1:
        return "Error: limit must be at least 1."
    if b"\x00" in data[:_BINARY_SNIFF_BYTES]:
        return f"Error: {file_path!r} is a binary file."
    if len(data) > MAX_FILE_BYTES:
        return f"Error: {file_path!r} is too large to read ({len(data)} bytes; limit {MAX_FILE_BYTES})."
    lines = _git_lines(data.decode("utf-8", errors="replace"))
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
        f"[{file_path}: {len(lines)} lines, {len(data)} bytes; showing lines {start}-{end}. "
        "Use offset and limit to read other ranges.]"
    )
    return "\n".join([header, *window])
