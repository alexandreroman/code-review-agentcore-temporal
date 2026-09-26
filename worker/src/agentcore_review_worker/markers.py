"""Hidden markers that make GitHub side effects idempotent and findings traceable."""

import re

_FINDING = re.compile(r"<!-- finding:(F-\d+) -->")


def finding_marker(finding_id: str) -> str:
    return f"<!-- finding:{finding_id} -->"


def round_marker(workflow_id: str, round_number: int) -> str:
    return f"<!-- round:{workflow_id}:{round_number} -->"


def closing_marker(workflow_id: str) -> str:
    return f"<!-- closing:{workflow_id} -->"


def fix_trailer(workflow_id: str, fix_number: int) -> str:
    return f"Review-Fix: {workflow_id}/{fix_number}"


def extract_finding_ids(text: str | None) -> list[str]:
    return _FINDING.findall(text or "")
