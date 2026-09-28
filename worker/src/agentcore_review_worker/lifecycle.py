"""Pure rules of the pull request lifecycle: what to do next, and how reviewer reports become open findings.

PullRequestWorkflow calls these from workflow code, so they stay deterministic and free of I/O.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from agentcore_review_shared.contract import (
    Category,
    CommentPosted,
    DismissedFinding,
    Finding,
    FixRequested,
    PullRequestState,
    format_finding_id,
    parse_finding_id,
)

from agentcore_review_worker.models import ReviewerReport, ReviewSummary, SynthesisInput, ThreadComment
from agentcore_review_worker.summaries import count

Action = Literal["close", "review", "fix", "reply"]

MAX_DELIVERIES = 50
"""Deliveries remembered to deduplicate fix requests and replies; redeliveries come within minutes, not 50 later."""

MAX_PENDING_REPLIES = 20
"""Replies queued behind a review or a fix; beyond that, the oldest are dropped."""

MAX_DISMISSED = 50
"""Dismissed findings remembered, and shown to later reviewers so they do not report them again."""

MAX_RESOLVED_THREADS = 50
"""Threads of resolved findings remembered, so that a late reply there still gets an answer."""

MAX_BOT_REPLIES_PER_THREAD = 3
"""The bot's answers in one thread before it hands over to a human: keeps a discussion from looping."""


def id_sort_key(finding_id: str) -> tuple[int, int, str]:
    """By category (security first), then by number: S-09, S-10, S-100, P-01.

    Any other ID, such as a legacy F-003, comes last. The ID itself breaks ties, so the order never depends on the
    input order, which a set leaves random.
    """
    parsed = parse_finding_id(finding_id)
    if parsed is None:
        return (len(Category), 0, finding_id)
    category, number = parsed
    return (list(Category).index(category), number, finding_id)


def sort_key(finding: Finding) -> tuple:
    """Most severe first, then in ID order."""
    return (finding.severity.rank, id_sort_key(finding.id))


def next_action(state: PullRequestState, closed: bool) -> Action | None:
    """Close first, then a pending review, then a pending fix, then a pending reply."""
    if closed:
        return "close"
    if state.pending_head_sha is not None and state.pending_head_sha != state.last_reviewed_sha:
        return "review"
    if state.pending_fixes:
        return "fix"
    if state.pending_replies:
        return "reply"
    return None


@dataclass(frozen=True)
class IdleTimer:
    """Where an idle period stands: its next step, its start, and the time left until the step is due."""

    step: Literal["warning", "close"]
    since: datetime  # keys the markers of the period's comments
    left: timedelta  # zero or less: due now


def start_idle(state: PullRequestState, now: datetime) -> None:
    """Any activity starts a new idle period: a new countdown, and a new warning to come."""
    state.idle_since = now
    state.idle_warned = False


def idle_timer(state: PullRequestState, now: datetime, warning_seconds: int, close_seconds: int) -> IdleTimer:
    """Where the idle period stands: the warning comes first, once, then the close.

    Both deadlines count from idle_since, so a continue-as-new or a late worker never pushes them back.
    Past the close deadline, the pull request closes without a warning that would announce minutes left.
    """
    since = state.idle_since
    if since is None:
        raise ValueError("no idle period started: call start_idle first")
    idle = now - since
    close_left = timedelta(seconds=close_seconds) - idle
    if state.idle_warned or close_left <= timedelta(0):
        return IdleTimer("close", since, close_left)
    return IdleTimer("warning", since, timedelta(seconds=warning_seconds) - idle)


def record_head(state: PullRequestState, head_sha: str, reviewing_sha: str | None = None) -> bool:
    """Record a pushed head as the pending review, unless it is already reviewed, under review or pending.

    Webhooks arrive in any order and may be redelivered; the round reviews the real head anyway,
    so a pending SHA is only a trigger.
    """
    if head_sha in (state.last_reviewed_sha, state.pending_head_sha, reviewing_sha):
        return False
    state.pending_head_sha = head_sha
    return True


def record_fix_request(state: PullRequestState, request: FixRequested) -> bool:
    """Queue a fix request, unless its webhook delivery was already seen.

    Requests stay apart until the fix starts: triage_fixes checks each one on its own, so a refused request
    never widens the others.
    """
    if request.delivery_id in state.fix_deliveries:
        return False
    recent = state.fix_deliveries + [request.delivery_id]
    state.fix_deliveries = recent[-MAX_DELIVERIES:]
    state.pending_fixes = state.pending_fixes + [request]
    return True


def record_reply(state: PullRequestState, reply: CommentPosted) -> bool:
    """Queue a reply to a finding, unless its webhook delivery was already seen; the oldest replies are dropped."""
    if reply.delivery_id in state.reply_deliveries:
        return False
    recent = state.reply_deliveries + [reply.delivery_id]
    state.reply_deliveries = recent[-MAX_DELIVERIES:]
    queued = state.pending_replies + [reply]
    state.pending_replies = queued[-MAX_PENDING_REPLIES:]
    return True


@dataclass(frozen=True)
class FixRefusal:
    """A /fix request that fixes nothing, with what its explanation needs."""

    request: FixRequested
    # In a finding's thread: the thread's finding, the only one the request may name. None in the Conversation.
    thread_finding_id: str | None = None
    # In the Conversation: the requested IDs that are not open findings.
    not_open_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FixTriage:
    """What the pending /fix requests amount to: one fixer run over the accepted requests' findings."""

    accepted: list[FixRequested]
    findings: list[Finding]  # in the order of the open findings
    refusals: list[FixRefusal]
    # Threads of requests whose thread has no open finding: those of dismissed or resolved findings get an answer.
    closed_threads: list[int]


def triage_fixes(state: PullRequestState, requests: list[FixRequested]) -> FixTriage:
    """Check each request against the open findings, then gather the accepted ones into one fix.

    In the Conversation, a bare /fix asks for every open finding, and named findings must all be open.
    In a finding's thread, a bare /fix asks for that finding, and the only finding it may name is that one.
    A request refused on any finding fixes none of them.
    """
    open_ids = [f.id for f in state.open_findings]
    wanted: set[str] = set()
    accepted: list[FixRequested] = []
    refusals: list[FixRefusal] = []
    closed_threads: list[int] = []
    for request in requests:
        if request.thread_root_id is None:
            not_open = [finding_id for finding_id in request.finding_ids if finding_id not in open_ids]
            if not_open:
                refusals.append(FixRefusal(request, not_open_ids=not_open))
                continue
            wanted.update(request.finding_ids or open_ids)
            accepted.append(request)
            continue
        thread_finding = open_finding_in_thread(state, request.thread_root_id)
        if thread_finding is None:
            closed_threads.append(request.thread_root_id)
            continue
        if any(finding_id != thread_finding.id for finding_id in request.finding_ids):
            refusals.append(FixRefusal(request, thread_finding_id=thread_finding.id))
            continue
        wanted.add(thread_finding.id)
        accepted.append(request)
    return FixTriage(
        accepted=accepted,
        findings=[f for f in state.open_findings if f.id in wanted],
        refusals=refusals,
        closed_threads=list(dict.fromkeys(closed_threads)),
    )


def open_finding_in_thread(state: PullRequestState, thread_root_id: int) -> Finding | None:
    """The open finding whose review thread starts with this comment."""
    for f in state.open_findings:
        if f.comment_id == thread_root_id:
            return f
    return None


def closed_finding_id(state: PullRequestState, thread_root_id: int) -> str | None:
    """The ID of the dismissed or resolved finding whose thread this is, so a late reply gets a short answer."""
    for dismissed in state.dismissed_findings:
        if dismissed.finding.comment_id == thread_root_id:
            return dismissed.finding.id
    return state.resolved_threads.get(thread_root_id)


def record_resolved(state: PullRequestState, finding_ids: list[str]) -> None:
    """Remember the threads of the open findings a round resolved; call it before they leave the open ones."""
    threads = dict(state.resolved_threads)
    for f in state.open_findings:
        if f.id in finding_ids and f.comment_id is not None:
            threads[f.comment_id] = f.id
    recent = list(threads.items())[-MAX_RESOLVED_THREADS:]
    state.resolved_threads = dict(recent)


def dismiss(state: PullRequestState, finding_id: str, reason: str, by: str) -> None:
    """Move an open finding to the dismissed ones; unknown IDs are ignored."""
    for f in state.open_findings:
        if f.id == finding_id:
            state.open_findings = [other for other in state.open_findings if other.id != finding_id]
            entry = DismissedFinding(finding=f, reason=reason, dismissed_by=by)
            recent = state.dismissed_findings + [entry]
            state.dismissed_findings = recent[-MAX_DISMISSED:]
            return


def discussion_thread(
    comments: list[ThreadComment], bot_login: str, author: str, up_to_comment_id: int
) -> list[ThreadComment]:
    """What the discussion agent reads: the bot's comments and the author's, up to the reply it answers.

    Anyone else's comments stay out: on a public repository, a bystander could otherwise speak to the agent.
    """
    kept: list[ThreadComment] = []
    for comment in comments:
        if comment.author in (bot_login, author):
            kept.append(comment)
        if comment.id == up_to_comment_id:
            break
    return kept


def clean_report(report: ReviewerReport, category: Category, open_ids: list[str]) -> ReviewerReport:
    """Pin every finding to the reviewer's category and keep only resolved IDs it was asked about."""
    resolved = {raw.strip().upper() for raw in report.resolved_ids} & set(open_ids)
    return ReviewerReport(
        findings=[draft.model_copy(update={"category": category}) for draft in report.findings],
        resolved_ids=sorted(resolved, key=id_sort_key),
    )


def number_findings(
    reports: list[ReviewerReport], last_numbers: dict[Category, int]
) -> tuple[list[Finding], dict[Category, int]]:
    """Stable IDs, numbered per category in report order; the reports come in a fixed order (category, then batch).

    Returns the findings and the last number of each category, which the state takes once the review is published.
    """
    numbers = dict(last_numbers)
    findings: list[Finding] = []
    for report in reports:
        for draft in report.findings:
            number = numbers.get(draft.category, 0) + 1
            numbers[draft.category] = number
            findings.append(Finding(**draft.model_dump(), id=format_finding_id(draft.category, number)))
    return findings, numbers


def resolved_ids(reports: list[ReviewerReport]) -> list[str]:
    return sorted({finding_id for report in reports for finding_id in report.resolved_ids}, key=id_sort_key)


def apply_summary(new: list[Finding], summary: ReviewSummary) -> list[Finding]:
    """The round's findings without duplicates, in the synthesis order; unknown IDs are ignored.

    A synthesis that marks every finding as a duplicate is ignored on that point: a duplicate
    always repeats a finding that stays.
    """
    by_id = {f.id: f for f in new}
    dropped = set(summary.duplicates) & by_id.keys()
    if dropped == by_id.keys():
        dropped = set()
    ordered = [by_id[i] for i in dict.fromkeys(summary.ordered_ids) if i in by_id and i not in dropped]
    placed = {f.id for f in ordered} | dropped
    return ordered + sorted((f for f in new if f.id not in placed), key=sort_key)


def fallback_summary(input: SynthesisInput) -> ReviewSummary:
    """Deterministic stand-in for the synthesis agent: sort by severity, deduplicate by path and line."""
    most_severe: dict[tuple[str, int], Finding] = {}
    for f in input.new_findings:
        key = (f.path, f.line)
        if key not in most_severe or f.severity.rank < most_severe[key].severity.rank:
            most_severe[key] = f
    merged = sorted(most_severe.values(), key=sort_key)
    kept = {f.id for f in merged}
    if merged:
        listed = ", ".join(f"{f.id} ({f.severity})" for f in merged)
        text = f"{count(len(merged), 'new finding')} in this round, most severe first: {listed}."
    else:
        text = "No new finding in this round."
    return ReviewSummary(
        summary_markdown=text,
        ordered_ids=[f.id for f in merged],
        duplicates=[f.id for f in input.new_findings if f.id not in kept],
    )


def merge_status(open_findings: list[Finding]) -> str:
    """Whether the open findings let the pull request merge: none of critical or high severity may be open."""
    blocking = [f.id for f in sorted(open_findings, key=sort_key) if f.severity.blocking]
    if blocking:
        findings = count(len(blocking), "critical or high finding")
        return f"**Merge blocked** by {findings}: {', '.join(blocking)}."
    return "**Mergeable**: no critical or high finding is open."


def current_details(phase: str, state: PullRequestState) -> str:
    """The current details shown in Temporal UI (Markdown): the phase and its round, the merge status, the open count.

    A worker serves them, so they show only while one runs: the memo holds the same state for when none does.
    """
    heading = f"**{phase[:1].upper()}{phase[1:]}**"
    # Phases such as "reviewing round 3" name the round already.
    if state.round > 0 and f"round {state.round}" not in phase:
        heading += f" · round {state.round}"
    open_count = len(state.open_findings)
    open_line = f"{count(open_count, 'open finding')}." if open_count else "No open finding."
    return "\n\n".join([heading, merge_status(state.open_findings), open_line])


def memo(phase: str, state: PullRequestState) -> dict[str, object]:
    """The memo shown in Temporal UI, readable even when no worker runs."""
    return {
        "state": phase,
        "round": state.round,
        "open_findings": [
            f"{f.id} {f.severity} {f.path}:{f.line} {f.title}" for f in sorted(state.open_findings, key=sort_key)
        ],
    }
