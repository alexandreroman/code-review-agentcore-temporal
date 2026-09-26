"""Deterministic finding bookkeeping: IDs, check colour, fallback synthesis, inline placement."""

from typing import Literal

from agentcore_review_shared.contract import Finding, FindingDraft

from agentcore_review_worker.hunks import is_commentable


def format_finding_id(number: int) -> str:
    return f"F-{number:03d}"


def assign_ids(drafts: list[FindingDraft], next_number: int) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    for draft in drafts:
        findings.append(Finding(**draft.model_dump(), id=format_finding_id(next_number)))
        next_number += 1
    return findings, next_number


def check_conclusion(open_findings: list[Finding]) -> Literal["success", "failure"]:
    return "failure" if any(f.severity.blocking for f in open_findings) else "success"


def sort_key(finding: Finding) -> tuple:
    return (finding.severity.rank, finding.path, finding.line, finding.id)


def fallback_merge(findings: list[Finding]) -> list[Finding]:
    best: dict[tuple[str, int], Finding] = {}
    for f in findings:
        key = (f.path, f.line)
        if key not in best or f.severity.rank < best[key].severity.rank:
            best[key] = f
    return sorted(best.values(), key=sort_key)


def split_inline(
    findings: list[Finding], commentable: dict[str, set[int]], max_inline: int = 20
) -> tuple[list[Finding], list[Finding]]:
    inline: list[Finding] = []
    body: list[Finding] = []
    for f in sorted(findings, key=sort_key):
        if len(inline) < max_inline and is_commentable(commentable.get(f.path, set()), f.line, f.end_line):
            inline.append(f)
        else:
            body.append(f)
    return inline, body
