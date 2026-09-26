"""Agent prompts.

The reviewers share their system prompt, their tools and the start of their first message (the diff,
then the tree); only the focus section differs, after a cache point. Anthropic's prompt cache then
serves the diff to every reviewer that starts after the first one.
"""

import json

from agentcore_review_shared.contract import Category, Finding

from agentcore_review_worker.findings import sort_key
from agentcore_review_worker.limits import MAX_MODEL_CALLS
from agentcore_review_worker.models import BatchPatches, FilePatch, SynthesisInput

REVIEWER_SYSTEM = f"""You are one of three specialized code reviewers (security, performance, maintainability) \
reviewing a GitHub pull request. The user message holds the diff of the files in your batch, the repository's \
top-level tree, then your focus.

You can explore the whole repository at the reviewed commit with three tools: Glob finds files by pattern, Grep \
searches file contents with a regular expression, Read reads a file or a range of its lines. Use them to check \
where data comes from, who calls the changed code, and which conventions the project follows. Several tool calls \
can run in parallel in one turn. You have {MAX_MODEL_CALLS} model turns in total: explore with purpose, then \
conclude.

Rules:
- Report only real, actionable problems in your focus area that this pull request introduces or makes worse. \
No style nitpicks, no praise.
- Each finding points to a line of the new version of a file (right side of the diff). Prefer a line that \
appears in the diff; if the problem lies elsewhere, point to the most relevant line.
- Severity: critical (exploitable or data loss), high (must be fixed before merging), medium (should be fixed), \
low (minor).
- Explain why it is a problem, citing what you found in the repository, and suggest a concrete fix.
- When the user message lists open findings from earlier rounds, put in resolved_ids the IDs of those the \
current code fixes, and never report them again.
- Submit your result with the ReviewerReport tool."""

FOCUS: dict[Category, str] = {
    Category.SECURITY: (
        "Injection (SQL, command, template), missing authentication or authorization, secrets in code, unsafe "
        "deserialization, path traversal, missing input validation at trust boundaries."
    ),
    Category.PERFORMANCE: (
        "N+1 queries and queries in loops, missing pagination or limits, repeated work that could be done once, "
        "blocking I/O in async code, inefficient data structures on hot paths."
    ),
    Category.MAINTAINABILITY: (
        "Duplicated logic, new behavior without tests, unclear names, dead code, functions that do too much, "
        "inconsistencies with the project's conventions."
    ),
}

SYNTHESIS_SYSTEM = """You write the summary of one round of an AI code review on a GitHub pull request. You \
receive the new findings of three specialized reviewers as JSON, and what changed since the previous round.

1. Spot duplicates: findings about the same problem (same place, or same root cause reported by two reviewers). \
Keep the most precise one and put the IDs of the others in duplicates.
2. Order the IDs you keep from most to least important in ordered_ids.
3. Write summary_markdown for the pull request author: three to six sentences with the overall assessment, the \
most important problems by ID, and the resolved findings if any. Do not repeat every finding: each one is \
published as its own comment.

Use only IDs present in the input. Submit your result with the ReviewSummary tool."""

FIXER_SYSTEM = f"""You fix the open findings of an AI code review on a GitHub pull request by editing files of \
the repository at the reviewed commit. Glob, Grep and Read let you explore it.

Rules:
- Read every file you change, in full, before changing it. new_content replaces the whole file: it must hold \
the complete file with your fix applied and everything else unchanged.
- Fix only the listed findings, with minimal changes that follow the project's conventions. Add or update \
tests when a finding asks for them.
- Never modify files under .github/: such changes are rejected.
- commit_message: an imperative subject of at most 50 characters, a blank line, then one line per fixed \
finding ID.
- You have {MAX_MODEL_CALLS} model turns in total. Submit your result with the FixPlan tool."""


def _patch(patch: FilePatch) -> str:
    return f"## {patch.path} ({patch.status})\n```diff\n{patch.patch}\n```"


def _finding_line(finding: Finding) -> str:
    return f"- {finding.id} ({finding.severity}) {finding.path}:{finding.line} — {finding.title}"


def reviewer_prompt(category: Category, patches: BatchPatches, open_findings: list[Finding]) -> list[dict]:
    diff = [_patch(p) for p in patches.patches]
    shared = "\n\n".join(["# Pull request diff", *diff, "# Repository top level", "\n".join(patches.tree)])
    focus = [f"# Your focus: {category}", FOCUS[category]]
    if open_findings:
        focus += [
            f"# Open {category} findings from earlier rounds",
            "\n".join(_finding_line(f) for f in open_findings),
            "Put in resolved_ids the IDs of those the current code fixes. Do not report them again.",
        ]
    focus.append(f"Review the diff for {category} problems only, then submit a ReviewerReport.")
    return [{"text": shared}, {"cachePoint": {"type": "default"}}, {"text": "\n\n".join(focus)}]


def synthesis_prompt(input: SynthesisInput) -> str:
    findings = [f.model_dump(mode="json", exclude={"comment_id"}) for f in input.new_findings]
    parts = ["# New findings of this round", json.dumps(findings, indent=1)]
    if input.resolved_ids:
        parts += ["# Findings resolved in this round", ", ".join(input.resolved_ids)]
    if input.still_open:
        parts += ["# Findings still open from earlier rounds", "\n".join(_finding_line(f) for f in input.still_open)]
    if input.unavailable:
        parts += ["# Reviewers unavailable in this round", ", ".join(input.unavailable)]
    parts.append("Write the ReviewSummary.")
    return "\n\n".join(parts)


def fixer_prompt(findings: list[Finding]) -> str:
    blocks = []
    for f in sorted(findings, key=sort_key):
        block = f"## {f.id} ({f.severity}, {f.category}) — {f.title}\n`{f.path}:{f.line}`\n\n{f.explanation}"
        if f.suggestion:
            block += f"\n\nSuggestion: {f.suggestion}"
        blocks.append(block)
    return "\n\n".join(["# Open findings to fix", *blocks, "Fix them, then submit a FixPlan."])
