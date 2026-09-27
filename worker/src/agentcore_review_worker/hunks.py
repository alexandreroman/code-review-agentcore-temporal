"""Which lines of a unified patch GitHub accepts for review comments (RIGHT side)."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def git_lines(text: str) -> list[str]:
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


def commentable_lines(patch: str | None) -> set[int]:
    lines: set[int] = set()
    if not patch:
        return lines
    current: int | None = None
    for raw in git_lines(patch):
        match = _HUNK.match(raw)
        if match:
            current = int(match.group(1))
            continue
        if current is None or raw.startswith("\\") or raw.startswith("-"):
            continue
        lines.add(current)
        current += 1
    return lines


def is_commentable(lines: set[int], line: int, end_line: int | None = None) -> bool:
    last = line if end_line is None else end_line
    # An inverted range would make all() below vacuously true, and GitHub rejects such a comment.
    if last < line:
        return False
    return all(number in lines for number in range(line, last + 1))
