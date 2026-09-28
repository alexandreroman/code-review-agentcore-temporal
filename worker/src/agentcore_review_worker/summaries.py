"""What Temporal UI shows next to an activity or a child workflow: its summary and details (user metadata).

The activity type or workflow type is the label (Read, PublishReview, ReviewerWorkflow); the summary only
holds the detail of the call, on a single line: paths, patterns, short SHAs, finding IDs, counts and round
numbers, never file contents or comment bodies. The Timeline truncates beyond 120 characters and Temporal
caps a summary at 200 bytes. Pure formatting: workflow code calls these functions.
"""

from typing import Any

from agentcore_review_shared.contract import Finding

from agentcore_review_worker.models import SynthesisInput

MAX_SUMMARY_CHARS = 120
MAX_SUMMARY_BYTES = 200
MAX_LIST_ITEMS = 20
SHORT_SHA = 7


def fit(text: str) -> str:
    """Make text a single line of at most 120 characters and 200 bytes, cutting its middle to keep a file name."""
    single_line = " ".join(text.split())
    limit = MAX_SUMMARY_CHARS
    shortened = _cut_middle(single_line, limit)
    # Non-ASCII characters take up to 4 bytes: shrink until the UTF-8 form fits too.
    while len(shortened.encode()) > MAX_SUMMARY_BYTES:
        limit -= 10
        shortened = _cut_middle(single_line, limit)
    return shortened


def _cut_middle(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = (limit - 1) // 2
    tail = limit - 1 - head
    return f"{text[:head]}…{text[len(text) - tail :]}"


def short_sha(sha: str) -> str:
    return sha[:SHORT_SHA]


def count(number: int, noun: str) -> str:
    """`1 file`, `3 files`."""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"


def finding_ids(ids: list[str]) -> str:
    """`F-001, F-002, …`: the first whole IDs that fit."""
    return _list_while_fits("", ids)


def _list_while_fits(prefix: str, items: list[str]) -> str:
    """The prefix, then the first items that fit (at least one), ending with `, …` when some are left out."""
    shown = items[:1]
    for end in range(2, len(items) + 1):
        more = ", …" if end < len(items) else ""
        if len(prefix + ", ".join(items[:end]) + more) > MAX_SUMMARY_CHARS:
            break
        shown = items[:end]
    listed = ", ".join(shown)
    if len(shown) < len(items):
        listed += ", …"
    return fit(prefix + listed)


# --- activities of the pull request workflow and its children ---


def pull_request(number: int) -> str:
    return f"pr-{number}"


def list_files(since_sha: str | None) -> str:
    return f"since {short_sha(since_sha)}" if since_sha is not None else "whole PR"


def check(round_number: int, status: str, conclusion: str | None) -> str:
    """`round 2 in progress`, `round 2 success`."""
    state = conclusion if status == "completed" and conclusion is not None else status.replace("_", " ")
    return f"round {round_number} {state}"


def publish(round_number: int, findings: int, inline: bool) -> str:
    """`round 2, 3 findings`, with `, no inline` for the fallback that puts every finding in the review body."""
    summary = f"round {round_number}, {count(findings, 'finding')}"
    return summary if inline else f"{summary}, no inline"


def commit(fix_number: int, files: int) -> str:
    return f"fix {fix_number}, {count(files, 'file')}"


def diff_files(paths: list[str]) -> str:
    """`3 files: app/main.py, app/models.py, …`: the first paths that fit, at least one."""
    return _list_while_fits(f"{count(len(paths), 'file')}: ", paths)


# --- navigation tools: from the arguments the model passed, which may be missing or invalid ---


def tool_call(tool_name: str, tool_input: Any) -> str | None:
    """The summary of a Read, Grep or Glob call; None when the arguments hold nothing to show.

    Never raises: a bad tool call must still reach the activity, which returns its error to the model.
    """
    try:
        return _tool_call(tool_name, tool_input)
    except Exception:
        # The arguments come from the model and the summary is cosmetic: an input the builders did not foresee
        # must not fail the workflow task that schedules the tool call.
        return None


def _tool_call(tool_name: str, tool_input: Any) -> str | None:
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Read":
        return _read_call(tool_input)
    if tool_name == "Grep":
        return _grep_call(tool_input)
    if tool_name == "Glob":
        return _glob_call(tool_input)
    return None


def _read_call(tool_input: dict[str, Any]) -> str | None:
    """`app/main.py:1-400`, `app/main.py:120-`, or the path alone when no valid line range was given."""
    path = _text(tool_input.get("file_path"))
    if path is None:
        return None
    offset = _positive_int(tool_input.get("offset"))
    limit = _positive_int(tool_input.get("limit"))
    if offset is not None and limit is not None:
        return fit(f"{path}:{offset}-{offset + limit - 1}")
    if offset is not None:
        return fit(f"{path}:{offset}-")
    if limit is not None:
        return fit(f"{path}:1-{limit}")
    return fit(path)


def _grep_call(tool_input: dict[str, Any]) -> str | None:
    """`/select\\(/ in app/ (*.py)`, leaving out the parts the model did not give."""
    parts = []
    pattern = _text(tool_input.get("pattern"))
    if pattern is not None:
        parts.append(f"/{pattern}/")
    path = _text(tool_input.get("path"))
    if path is not None:
        parts.append(f"in {path}")
    glob = _text(tool_input.get("glob"))
    if glob is not None:
        parts.append(f"({glob})")
    return fit(" ".join(parts)) if parts else None


def _glob_call(tool_input: dict[str, Any]) -> str | None:
    """`app/**/*.py`, followed by `in <path>` when a directory was given."""
    parts = []
    pattern = _text(tool_input.get("pattern"))
    if pattern is not None:
        parts.append(pattern)
    path = _text(tool_input.get("path"))
    if path is not None:
        parts.append(f"in {path}")
    return fit(" ".join(parts)) if parts else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _positive_int(value: Any) -> int | None:
    """The value as an int of at least 1, converted like navigation._coerce_int does for Read; None otherwise."""
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except TypeError, ValueError, OverflowError:
        return None
    return number if number >= 1 else None


# --- child workflow details (Markdown) ---


def _bullet_list(items: list[str]) -> str:
    """A Markdown list of at most 20 items, then how many were left out."""
    lines = [f"- {item}" for item in items[:MAX_LIST_ITEMS]]
    left_out = len(items) - MAX_LIST_ITEMS
    if left_out > 0:
        lines.append(f"- … and {left_out} more")
    return "\n".join(lines)


def file_list(paths: list[str]) -> str:
    return _bullet_list([f"`{path}`" for path in paths])


def finding_line(finding: Finding) -> str:
    """`**F-001** · critical · security — SQL injection in the search query`."""
    return f"**{finding.id}** · {finding.severity} · {finding.category} — {fit(finding.title)}"


def finding_list(findings: list[Finding]) -> str:
    return _bullet_list([finding_line(finding) for finding in findings])


def synthesis_details(input: SynthesisInput) -> str:
    return _bullet_list(
        [
            f"New findings: {len(input.new_findings)}",
            f"Still open: {len(input.still_open)}",
            f"Resolved: {len(input.resolved_ids)}",
            f"Unavailable reviewers: {len(input.unavailable)}",
        ]
    )
