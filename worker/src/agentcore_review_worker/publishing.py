"""What the bot writes on GitHub: review comments and body, check output, thread replies, /fix refusals and
failures, closing and inactivity comments, fixer changes.

Pure functions: the activities call them with data they fetched, the workflow with its state.
"""

import re
from collections.abc import Sequence
from pathlib import PurePosixPath

from agentcore_review_shared.contract import FINDING_ID_PATTERN
from pydantic import BaseModel

from agentcore_review_worker.hunks import is_commentable
from agentcore_review_worker.lifecycle import MAX_BOT_REPLIES_PER_THREAD, merge_status, sort_key, with_severity
from agentcore_review_worker.markers import finding_marker
from agentcore_review_worker.models import (
    CheckOutput,
    DiscussionReply,
    FileChange,
    Finding,
    ReviewContent,
    ThreadComment,
)
from agentcore_review_worker.navigation import is_outside_repository
from agentcore_review_worker.summaries import count, file_list

MAX_INLINE_COMMENTS = 20
MAX_BODY_CHARS = 60_000  # GitHub rejects review bodies over 65,536 characters
PROTECTED_DIR = ".github"  # the app has no workflows permission, and the fixer must not touch CI

_VERDICT_LINE = re.compile(rf"\*\*{FINDING_ID_PATTERN} (stays open|dismissed)\.\*\*")  # how reply_body starts


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


def _split_inline(
    findings: list[Finding], commentable: dict[str, set[int]], cap: int
) -> tuple[list[Finding], list[Finding]]:
    """The findings to attach inline (at most `cap`, on commentable diff lines) and the ones for the body."""
    inline: list[Finding] = []
    body: list[Finding] = []
    for f in sorted(findings, key=sort_key):
        if len(inline) < cap and is_commentable(commentable.get(f.path, set()), f.line, f.end_line):
            inline.append(f)
        else:
            body.append(f)
    return inline, body


def build_review(content: ReviewContent, commentable: dict[str, set[int]], marker: str, inline: bool) -> ReviewPayload:
    """One COMMENT review: findings on diff lines inline (at most 20), all others in the body.

    With inline=False (after GitHub refused the inline comments with a 422), every finding goes
    into the body.
    """
    cap = MAX_INLINE_COMMENTS if inline else 0
    attached, in_body = _split_inline(content.findings, commentable, cap)
    sections = [
        marker,
        f"## AI Review — round {content.round}",
        merge_status(content.findings + content.still_open),
        content.summary_markdown.strip() or "No summary.",
    ]
    if in_body:
        sections.append("### Other findings" if attached else "### Findings")
        sections += [comment_body(f) for f in in_body]
    if content.resolved_ids:
        sections.append("### Resolved in this round\n\n" + ", ".join(content.resolved_ids))
    if content.still_open:
        still_open = "\n".join(_line(f) for f in sorted(content.still_open, key=sort_key))
        sections.append("### Still open from earlier rounds\n\n" + still_open)
    not_reviewed = []
    if content.excluded:
        not_reviewed.append(file_list(content.excluded))
    if content.unlisted:
        not_reviewed.append(f"- {count(content.unlisted, 'more file')} that GitHub does not list: too many changes")
    if not_reviewed:
        sections.append("### Not reviewed\n\n" + "\n".join(not_reviewed))
    if content.unavailable:
        sections.append(
            "### Reviewers unavailable\n\n" + ", ".join(content.unavailable) + ": this round is published without them."
        )
    body = "\n\n".join(sections)
    if len(body) > MAX_BODY_CHARS:
        body = body[:MAX_BODY_CHARS] + "\n\n… (truncated)"
    return ReviewPayload(body=body, comments=[_inline(f) for f in attached])


def check_output(open_findings: list[Finding], *, unavailable: Sequence[str] = (), unlisted: int = 0) -> CheckOutput:
    """The output of a completed round's check: red while a critical or high finding is open.

    `unavailable` names the reviewers that failed, `unlisted` counts the changed files GitHub did not list.
    """
    ordered = sorted(open_findings, key=sort_key)
    blocking = [f for f in ordered if f.severity.blocking]
    if blocking:
        title = f"Merge blocked: {count(len(blocking), 'critical or high finding')} open"
        if len(ordered) > len(blocking):
            title += f" ({len(ordered)} in total)"
        lines = [_merge_blocked(blocking), ""] + [_line(f) for f in ordered]
    elif ordered:
        title = f"{count(len(ordered), 'open finding')}, none critical or high"
        lines = [_line(f) for f in ordered]
    else:
        title = "No open finding"
        lines = ["No finding is open."]
    if unavailable:
        title += f", {count(len(unavailable), 'reviewer')} unavailable"
        lines += ["", f"Not reviewed in this round (reviewer unavailable): {', '.join(unavailable)}."]
    if unlisted:
        files = count(unlisted, "file")
        title += f", {files} not listed"
        lines += ["", f"Not reviewed in this round (not listed by GitHub, too many changes): {files}."]
    return CheckOutput(conclusion="failure" if blocking else "success", title=title, summary="\n".join(lines))


def _merge_blocked(blocking: list[Finding]) -> str:
    """Why the check fails, and the ways to turn it green: a fix, or a dismissal in the finding's thread."""
    findings = count(len(blocking), "critical or high finding")
    found = f"**Merge blocked** by {findings}: {with_severity(blocking)}."
    if len(blocking) == 1:
        way_out = "Fix it (push a commit or comment `/fix`) or have it dismissed in its thread."
    else:
        way_out = "Fix them (push a commit or comment `/fix`) or have them dismissed in their thread."
    return f"{found} {way_out} The check turns green once none is left."


def unavailable_check_output(round_number: int, unavailable: list[str]) -> CheckOutput:
    """The output of a round where no reviewer completed: the head stays unreviewed."""
    summary = (
        f"No reviewer completed round {round_number} (unavailable: {', '.join(unavailable)}), "
        "so this head was not reviewed. Push a commit to retry."
    )
    return CheckOutput(conclusion="failure", title="Review unavailable", summary=summary)


def reply_body(finding_id: str, reply: DiscussionReply, marker: str) -> str:
    """The discussion agent's answer, after a verdict line that tells at a glance whether the finding stays."""
    verdict = "dismissed" if reply.verdict == "dismiss" else "stays open"
    return f"**{finding_id} {verdict}.** {reply.answer.strip()}\n\n{marker}"


def no_longer_open_reply(finding_id: str, marker: str) -> str:
    return f"{finding_id} is no longer open: nothing left to discuss here.\n\n{marker}"


def superseded_reply(marker: str) -> str:
    """Closes a finding thread of an earlier run: the new run's review takes over."""
    return f"A new review run takes over this pull request: its new review replaces this finding.\n\n{marker}"


def budget_reply(marker: str) -> str:
    return (
        f"I have answered {MAX_BOT_REPLIES_PER_THREAD} times in this thread: let's leave the rest to a human "
        f"reviewer. Comment `/fix` here to fix this finding.\n\n{marker}"
    )


def failed_reply(marker: str) -> str:
    return f"I could not answer this time. Reply again to retry.\n\n{marker}"


def _fix_command(finding_ids: list[str]) -> str:
    return " ".join(["/fix", *finding_ids])


def off_thread_fix_reply(thread_finding_id: str, requested_ids: list[str], marker: str) -> str:
    """A /fix in a finding's thread that named other findings."""
    command = _fix_command(requested_ids)
    return (
        f"This thread is about {thread_finding_id}: `{command}` was not applied. Comment `/fix` here to fix "
        f"{thread_finding_id}, or `{command}` in the conversation.\n\n{marker}"
    )


def not_open_fix_comment(not_open_ids: list[str], open_findings: list[Finding], marker: str) -> str:
    """A /fix in the Conversation that named findings that are not open."""
    if len(not_open_ids) == 1:
        refused = f"{not_open_ids[0]} is not an open finding"
    else:
        refused = f"{', '.join(not_open_ids)} are not open findings"
    if open_findings:
        listed = ", ".join(f.id for f in sorted(open_findings, key=sort_key))
        still_open = f"Open findings: {listed}."
    else:
        still_open = "No finding is open."
    return f"{refused}: nothing was fixed. {still_open}\n\n{marker}"


def failed_fix_comment(fix_number: int, error_type: str | None, marker: str) -> str:
    """A /fix that pushed nothing; error_type is the failure's ApplicationError type, if any."""
    if error_type == "BranchMoved":
        text = f"Fix {fix_number} abandoned: the branch changed while it was prepared. Comment `/fix` to try again."
    elif error_type == "ForkNotSupported":
        text = f"Fix {fix_number} not pushed: this pull request comes from a fork, which the bot cannot push to."
    else:
        text = f"Fix {fix_number} failed: nothing was pushed. Comment `/fix` to try again."
    return f"{text}\n\n{marker}"


def bot_answers(thread: list[ThreadComment], bot_login: str) -> int:
    """The discussion agent's answers in a thread: the bot's replies that start with a verdict line.

    The finding itself and the bot's other replies (failure, budget reached, no longer open) do not count.
    """
    return sum(1 for comment in thread if comment.author == bot_login and _VERDICT_LINE.match(comment.body))


def closing_comment(closed_by: str | None, open_findings: list[Finding], marker: str) -> str:
    ordered = sorted(open_findings, key=sort_key)
    listed = with_severity(ordered)
    still_open = count(len(ordered), "open finding")
    who = f" by @{closed_by}" if closed_by else ""
    if any(f.severity.blocking for f in ordered):
        return f"⚠️ Merged{who} bypassing AI Review, {still_open}: {listed}.\n\n{marker}"
    return f"Merged{who} with {still_open}: {listed}.\n\n{marker}"


def _duration(seconds: int) -> str:
    if seconds % 60 == 0:
        return count(seconds // 60, "minute")
    return count(seconds, "second")


def idle_warning_comment(warning_seconds: int, close_seconds: int, marker: str) -> str:
    return (
        f"No activity for {_duration(warning_seconds)}: this pull request will be closed in "
        f"{_duration(close_seconds - warning_seconds)}. Push a commit to keep it open.\n\n{marker}"
    )


def idle_close_comment(close_seconds: int, marker: str) -> str:
    return f"Closed after {_duration(close_seconds)} without activity. Reopen it for a new review.\n\n{marker}"


def _repository_path(raw: str) -> str | None:
    """The path in its plain form ("./src//A.java" gives "src/A.java"), or None when it is not a repository file."""
    text = raw.strip()
    if not text or is_outside_repository(text):
        return None
    parts = PurePosixPath(text).parts
    return "/".join(parts) if parts else None


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
