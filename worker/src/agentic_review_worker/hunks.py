"""Which lines of a unified patch GitHub accepts for review comments (RIGHT side)."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def commentable_lines(patch: str | None) -> set[int]:
    lines: set[int] = set()
    if not patch:
        return lines
    current: int | None = None
    for raw in patch.splitlines():
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
    if last < line:
        return False
    return all(number in lines for number in range(line, last + 1))
