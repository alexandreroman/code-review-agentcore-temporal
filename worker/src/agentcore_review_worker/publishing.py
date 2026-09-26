"""What the bot writes on GitHub: review comments and body, check output, closing comment, fix commit.

Pure functions: the activities call them with data they fetched, the workflow with its state.
"""

from collections.abc import Sequence
from pathlib import PurePosixPath

from agentcore_review_shared.contract import FileChange, Finding
from pydantic import BaseModel

from agentcore_review_worker.findings import sort_key, split_inline
from agentcore_review_worker.markers import finding_marker
from agentcore_review_worker.models import ReviewContent

MAX_INLINE_COMMENTS = 20
MAX_BODY_CHARS = 60_000  # GitHub rejects review bodies over 65,536 characters
MAX_LISTED_FILES = 30
PROTECTED_DIR = ".github"  # the app has no workflows permission, and the fixer must not touch CI


class InlineComment(BaseModel):
    path: str
    line: int
    side: str = "RIGHT"
    start_line: int | None = None
    start_side: str | None = None
    body: str


class ReviewPayload(BaseModel):
    body: str
    comments: list[InlineComment]


def comment_body(finding: Finding) -> str:
    parts = [
        finding_marker(finding.id),
        f"**{finding.id}** · {finding.severity} · {finding.category} — **{finding.title}**",
        "",
        finding.explanation,
    ]
    if finding.suggestion:
        parts += ["", f"**Suggestion:** {finding.suggestion}"]
    return "\n".join(parts)


def _inline(finding: Finding) -> InlineComment:
    if finding.end_line is not None and finding.end_line > finding.line:
        return InlineComment(
            path=finding.path,
            line=finding.end_line,
            start_line=finding.line,
            start_side="RIGHT",
            body=comment_body(finding),
        )
    return InlineComment(path=finding.path, line=finding.line, body=comment_body(finding))


def _line(finding: Finding) -> str:
    return f"- **{finding.id}** {finding.severity} · `{finding.path}:{finding.line}` · {finding.title}"


def _file_list(paths: list[str]) -> str:
    lines = [f"- `{p}`" for p in paths[:MAX_LISTED_FILES]]
    if len(paths) > MAX_LISTED_FILES:
        lines.append(f"- … and {len(paths) - MAX_LISTED_FILES} more")
    return "\n".join(lines)


def build_review(
    content: ReviewContent, commentable: dict[str, set[int]], marker: str, inline: bool = True
) -> ReviewPayload:
    """One COMMENT review: findings on diff lines inline (at most 20), all others in the body.

    With inline=False (after GitHub refused the inline comments with a 422), every finding goes
    into the body.
    """
    if inline:
        attached, in_body = split_inline(content.findings, commentable, MAX_INLINE_COMMENTS)
    else:
        attached, in_body = [], sorted(content.findings, key=sort_key)
    sections = [marker, f"## AI Review — round {content.round}", content.summary_markdown.strip() or "No summary."]
    if not content.findings:
        sections.append("No new finding in this round.")
    if in_body:
        sections.append("### Other findings" if inline else "### Findings")
        sections += [comment_body(f) for f in in_body]
    if content.resolved_ids:
        sections.append("### Resolved in this round\n\n" + ", ".join(content.resolved_ids))
    if content.still_open:
        still_open = "\n".join(_line(f) for f in sorted(content.still_open, key=sort_key))
        sections.append("### Still open from earlier rounds\n\n" + still_open)
    if content.excluded:
        sections.append("### Not reviewed\n\n" + _file_list(content.excluded))
    if content.unavailable:
        sections.append(
            "### Reviewers unavailable\n\n" + ", ".join(content.unavailable) + ": this round is published without them."
        )
    body = "\n\n".join(sections)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n\n… (truncated)"
    return ReviewPayload(body=body, comments=[_inline(f) for f in attached])


def check_output(open_findings: list[Finding], unavailable: Sequence[str] = ()) -> tuple[str, str]:
    """Title and summary of a completed round's check; `unavailable` names the reviewers that failed."""
    if open_findings:
        ordered = sorted(open_findings, key=sort_key)
        blocking = sum(f.severity.blocking for f in ordered)
        plural = "s" if len(ordered) != 1 else ""
        title = f"{len(ordered)} open finding{plural}, {blocking} blocking"
        lines = [_line(f) for f in ordered]
        lines += ["", "The check fails while a finding of high severity or above is open."]
    else:
        title = "No open finding"
        lines = ["No finding is open."]
    if unavailable:
        plural = "s" if len(unavailable) != 1 else ""
        title += f", {len(unavailable)} reviewer{plural} unavailable"
        lines += ["", f"Not reviewed in this round (reviewer unavailable): {', '.join(unavailable)}."]
    return title, "\n".join(lines)


def unavailable_check_output(round_number: int, unavailable: Sequence[str]) -> tuple[str, str]:
    """Title and summary of a round where no reviewer completed: the head stays unreviewed."""
    summary = (
        f"No reviewer completed round {round_number} (unavailable: {', '.join(unavailable)}), "
        "so this head was not reviewed. Push a commit to retry."
    )
    return "Review unavailable", summary


def closing_comment(closed_by: str | None, open_findings: list[Finding]) -> str:
    ordered = sorted(open_findings, key=sort_key)
    listed = ", ".join(f"{f.id} ({f.severity})" for f in ordered)
    count = f"{len(ordered)} open finding{'s' if len(ordered) != 1 else ''}"
    who = f" by @{closed_by}" if closed_by else ""
    if any(f.severity.blocking for f in ordered):
        return f"⚠️ Merged{who} bypassing AI Review, {count}: {listed}."
    return f"Merged{who} with {count}: {listed}."


def commit_message(message: str, trailer: str) -> str:
    return f"{message.rstrip()}\n\n{trailer}"


def _repository_path(raw: str) -> str | None:
    text = raw.strip()
    if not text or text.startswith("/"):
        return None
    parts = PurePosixPath(text).parts
    if not parts or ".." in parts:
        return None
    return "/".join(parts)


def split_changes(changes: list[FileChange]) -> tuple[list[FileChange], list[str]]:
    """The changes the fixer may push, and the rejected paths (outside the repository or under .github/).

    A path changed twice keeps its last content.
    """
    accepted: dict[str, FileChange] = {}
    rejected: list[str] = []
    for change in changes:
        path = _repository_path(change.path)
        if path is None or path.split("/", 1)[0].lower() == PROTECTED_DIR:
            rejected.append(change.path)
        else:
            accepted[path] = change.model_copy(update={"path": path})
    return list(accepted.values()), rejected
