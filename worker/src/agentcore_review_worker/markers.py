"""Hidden markers that make GitHub side effects idempotent and findings traceable."""

import re
from datetime import datetime

_FINDING = re.compile(r"<!-- finding:(F-\d+) -->")
_REPLY = re.compile(r"<!-- reply:\S+:\d+ -->")


def finding_marker(finding_id: str) -> str:
    return f"<!-- finding:{finding_id} -->"


def round_marker(workflow_id: str, round_number: int) -> str:
    return f"<!-- round:{workflow_id}:{round_number} -->"


def closing_marker(workflow_id: str) -> str:
    return f"<!-- closing:{workflow_id} -->"


def reply_marker(workflow_id: str, comment_id: int) -> str:
    """Marks the bot's reply to one human comment: posted once, whatever the retries."""
    return f"<!-- reply:{workflow_id}:{comment_id} -->"


def fix_refusal_marker(workflow_id: str, delivery_id: str) -> str:
    """Marks the bot's refusal of one /fix request, keyed on its webhook delivery: posted once, whatever the retries."""
    return f"<!-- fix-refused:{workflow_id}:{delivery_id} -->"


def idle_warning_marker(workflow_id: str, idle_since: datetime) -> str:
    """Marks the warning of one idle period, keyed on its start: posted once, whatever the retries or replays."""
    return f"<!-- idle-warning:{workflow_id}:{int(idle_since.timestamp())} -->"


def idle_close_marker(workflow_id: str, idle_since: datetime) -> str:
    """Marks the comment of a close for inactivity; a reopened pull request's next close gets its own."""
    return f"<!-- idle-close:{workflow_id}:{int(idle_since.timestamp())} -->"


def has_reply_marker(text: str) -> bool:
    return _REPLY.search(text) is not None


def fix_trailer(workflow_id: str, fix_number: int) -> str:
    return f"Review-Fix: {workflow_id}/{fix_number}"


def extract_finding_ids(text: str | None) -> list[str]:
    return _FINDING.findall(text or "")
