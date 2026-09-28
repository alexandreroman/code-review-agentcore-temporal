"""Hidden markers that make GitHub side effects idempotent and findings traceable."""

import re
from collections.abc import Iterable
from datetime import datetime

from agentcore_review_shared.contract import FINDING_ID_PATTERN, Category, parse_finding_id

_FINDING = re.compile(rf"<!-- finding:({FINDING_ID_PATTERN}) -->")


def finding_marker(finding_id: str) -> str:
    return f"<!-- finding:{finding_id} -->"


def round_marker(workflow_id: str, round_number: int) -> str:
    return f"<!-- round:{workflow_id}:{round_number} -->"


def closing_marker(workflow_id: str) -> str:
    return f"<!-- closing:{workflow_id} -->"


def reply_marker(workflow_id: str, comment_id: int) -> str:
    """Marks the bot's answer keyed on a comment (a reply, or a thread root): posted once, whatever the retries."""
    return f"<!-- reply:{workflow_id}:{comment_id} -->"


def fix_refusal_marker(workflow_id: str, delivery_id: str) -> str:
    """Marks the bot's refusal of one /fix request, keyed on its webhook delivery: posted once, whatever the retries."""
    return f"<!-- fix-refused:{workflow_id}:{delivery_id} -->"


def fix_failure_marker(workflow_id: str, fix_number: int) -> str:
    """Marks the bot's note on a failed fix, keyed on its number: posted once, whatever the retries."""
    return f"<!-- fix-failed:{workflow_id}:{fix_number} -->"


def idle_warning_marker(workflow_id: str, idle_since: datetime) -> str:
    """Marks the warning of one idle period, keyed on its start: posted once, whatever the retries or replays."""
    return f"<!-- idle-warning:{workflow_id}:{int(idle_since.timestamp())} -->"


def idle_close_marker(workflow_id: str, idle_since: datetime) -> str:
    """Marks the comment of a close for inactivity; a reopened pull request's next close gets its own."""
    return f"<!-- idle-close:{workflow_id}:{int(idle_since.timestamp())} -->"


def reopen_marker(workflow_id: str, run_id: str) -> str:
    """Marks the comment announcing the new review of a reopened pull request: once per run, whatever the retries."""
    return f"<!-- reopen:{workflow_id}:{run_id} -->"


def superseded_marker(workflow_id: str, thread_root_id: int) -> str:
    """Marks the note that closes an earlier run's finding thread once a new run takes over: posted once."""
    return f"<!-- superseded:{workflow_id}:{thread_root_id} -->"


def fix_trailer(workflow_id: str, fix_number: int) -> str:
    return f"Review-Fix: {workflow_id}/{fix_number}"


def extract_finding_ids(text: str | None) -> list[str]:
    return _FINDING.findall(text or "")


# --- the numbers an earlier run of the same workflow ID already used, read back from GitHub ---


def last_round(workflow_id: str, review_bodies: Iterable[str | None]) -> int:
    """The highest round among the round markers of this workflow ID; 0 when there is none."""
    pattern = re.compile(rf"<!-- round:{re.escape(workflow_id)}:(\d+) -->")
    return _highest(pattern, review_bodies)


def last_finding_numbers(texts: Iterable[str | None]) -> dict[Category, int]:
    """The highest finding number of each category among the finding markers (S-12 gives 12 for security).

    A category without a marker is absent.
    """
    last: dict[Category, int] = {}
    for text in texts:
        for finding_id in extract_finding_ids(text):
            parsed = parse_finding_id(finding_id)
            if parsed is None:
                continue
            category, number = parsed
            last[category] = max(last.get(category, 0), number)
    return last


def last_fix_number(workflow_id: str, commit_messages: Iterable[str | None]) -> int:
    """The highest fix number among the Review-Fix trailers of this workflow ID; 0 when there is none."""
    # A whole line, as the fixer's idempotence check reads it.
    pattern = re.compile(rf"^Review-Fix: {re.escape(workflow_id)}/(\d+)$", re.MULTILINE)
    return _highest(pattern, commit_messages)


def _highest(pattern: re.Pattern[str], texts: Iterable[str | None]) -> int:
    numbers = [int(number) for text in texts for number in pattern.findall(text or "")]
    return max(numbers, default=0)
