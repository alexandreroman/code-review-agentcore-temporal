"""Worker-internal models: findings, the pull request workflow's state, and what passes between the workflow, its
children and the activities.

The parent workflow only handles metadata (paths, SHAs, snapshot references): patches and file
contents appear only in the reviewer and fixer children.
"""

from datetime import datetime
from typing import Literal

from agentcore_review_shared.contract import (
    Category,
    CommentPosted,
    FixRequested,
    LenientEnum,
    PrRef,
    PullRequestInput,
)
from pydantic import BaseModel, Field

# Here rather than in agent_model so that workflow code can import it without agent_model's I/O libraries.
MODEL_NAME = "claude"
"""Name of the single model factory registered in StrandsPlugin and used by every TemporalAgent."""


class Severity(LenientEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        """0 is the most severe."""
        return list(Severity).index(self)

    @property
    def blocking(self) -> bool:
        """A blocking finding turns the AI Review check red."""
        return self in (Severity.CRITICAL, Severity.HIGH)


class FindingDraft(BaseModel):
    category: Category
    severity: Severity = Field(
        description="critical: exploitable or data loss; high: must be fixed before merging; "
        "medium: should be fixed; low: minor"
    )
    path: str = Field(description="File path relative to the repository root")
    line: int = Field(ge=1, description="Line in the new version of the file (right side of the diff)")
    end_line: int | None = Field(default=None, ge=1, description="Last line, when the finding spans several lines")
    title: str = Field(description="One-line summary")
    explanation: str = Field(description="Why this is a problem, citing what the repository shows")
    suggestion: str | None = Field(default=None, description="A concrete fix")


class Finding(FindingDraft):
    id: str
    comment_id: int | None = None


class DismissedFinding(BaseModel):
    finding: Finding
    reason: str
    dismissed_by: str


class PullRequestState(BaseModel):
    last_reviewed_sha: str | None = None
    # The commit of the last fix the bot pushed: a round whose head it is reviews that fix only.
    last_fix_sha: str | None = None
    pending_head_sha: str | None = None
    # Fix requests waiting for the next fix, in arrival order: each one is checked on its own when the fix starts.
    pending_fixes: list[FixRequested] = Field(default_factory=list)
    # Delivery IDs of the latest fix requests: GitHub redelivers webhooks, and a repeat must not fix twice.
    fix_deliveries: list[str] = Field(default_factory=list)
    pending_replies: list[CommentPosted] = Field(default_factory=list)
    reply_deliveries: list[str] = Field(default_factory=list)
    open_findings: list[Finding] = Field(default_factory=list)
    dismissed_findings: list[DismissedFinding] = Field(default_factory=list)
    # Finding ID by the comment starting its thread, for the latest findings a round resolved.
    resolved_threads: dict[int, str] = Field(default_factory=dict)
    # The round whose check covers last_reviewed_sha: a dismissal updates that check.
    last_reviewed_round: int | None = None
    round: int = 0
    fix_count: int = 0
    discussion_count: int = 0
    # The last finding number used in each category, absent until its first finding: S-03 leaves 3 for security.
    last_finding_numbers: dict[Category, int] = Field(default_factory=dict)
    # Start of the current idle period (the end of the last action, or the last signal) and whether its warning
    # was posted: kept in the state, so a continue-as-new does not restart the countdown.
    idle_since: datetime | None = None
    idle_warned: bool = False


class PullRequestRunInput(PullRequestInput):
    """The router's input plus the state: empty for a started run, carried over by a continue-as-new."""

    state: PullRequestState = Field(default_factory=PullRequestState)


class ChangedFile(BaseModel):
    path: str
    patch_bytes: int | None


class ChangeSet(BaseModel):
    head_sha: str
    pr_base_sha: str  # the base branch's SHA: inline comments must fit the whole pull request's diff
    diff_base: str  # the last reviewed SHA for a delta, pr_base_sha for the whole pull request
    files: list[ChangedFile] = Field(default_factory=list)  # reviewable files only
    excluded: list[str] = Field(default_factory=list)
    unlisted: int = 0  # changed files beyond the ones a GitHub comparison lists
    # A worker setting carried to workflow code, which cannot read the environment: riding on the ListFiles result,
    # it is read from the history on replay, so a changed setting never changes a replayed round.
    max_parallel_agents: int


class ListFilesInput(BaseModel):
    pr: PrRef
    since_sha: str | None = None


class SnapshotInput(BaseModel):
    pr: PrRef
    sha: str


class SnapshotRef(BaseModel):
    pr: PrRef
    sha: str
    bucket: str | None = None
    key: str | None = None  # None: archive over 200 MB, the tools read through the GitHub API


class BatchInput(BaseModel):
    pr: PrRef
    diff_base: str
    head_sha: str
    paths: list[str]


class FilePatch(BaseModel):
    path: str
    status: str
    patch: str


class BatchPatches(BaseModel):
    patches: list[FilePatch]
    tree: list[str]


class ReviewerInput(BaseModel):
    category: Category
    snapshot: SnapshotRef
    batch: BatchInput
    open_findings: list[Finding] = Field(default_factory=list)
    dismissed_findings: list[DismissedFinding] = Field(default_factory=list)
    fix_round: bool = False  # the diff is the bot's last fix: only critical or high problems in it count


class SynthesisInput(BaseModel):
    new_findings: list[Finding]
    still_open: list[Finding] = Field(default_factory=list)
    resolved_ids: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)


class FixerInput(BaseModel):
    pr: PrRef
    workflow_id: str
    fix_number: int
    expected_head_sha: str
    snapshot: SnapshotRef
    findings: list[Finding]


class ThreadComment(BaseModel):
    id: int
    author: str
    body: str


class DiscussionInput(BaseModel):
    finding: Finding
    thread: list[ThreadComment]  # the bot's comments and the author's, up to the reply to answer
    author: str  # the human to answer
    snapshot: SnapshotRef


# Structured outputs of the reviewer, synthesis, fixer and discussion agents: the field descriptions reach the model.


class ReviewerReport(BaseModel):
    findings: list[FindingDraft] = Field(default_factory=list)
    resolved_ids: list[str] = Field(
        default_factory=list, description="IDs of open findings from earlier rounds that the current code fixes"
    )


class ReviewSummary(BaseModel):
    summary_markdown: str = Field(description="Short Markdown summary of the round for the pull request author")
    ordered_ids: list[str] = Field(description="IDs of the findings to keep, most important first")
    duplicates: list[str] = Field(default_factory=list, description="IDs of findings that repeat another finding")


class FileChange(BaseModel):
    path: str = Field(description="File path relative to the repository root")
    new_content: str = Field(description="Complete new content of the file, not a diff")


class FixPlan(BaseModel):
    changes: list[FileChange] = Field(description="The changed files; empty when every finding is skipped")
    commit_message: str = Field(
        description="Imperative subject of at most 50 characters, a blank line, one line per fixed finding ID, "
        "then one line `Skipped <ID>: <one-line reason>` per skipped finding"
    )


class DiscussionReply(BaseModel):
    verdict: Literal["keep", "dismiss"] = Field(
        description="dismiss only when the code shows the finding is wrong or does not apply"
    )
    answer: str = Field(description="Markdown answer to the human, about 150 words at most")


class CheckOutput(BaseModel):
    """What a completed check shows."""

    conclusion: Literal["success", "failure"]
    title: str
    summary: str


class CheckInput(BaseModel):
    pr: PrRef
    head_sha: str
    external_id: str
    status: Literal["in_progress", "completed"]
    conclusion: Literal["success", "failure"] | None = None
    title: str = ""
    summary: str = ""


class ReviewContent(BaseModel):
    round: int
    summary_markdown: str
    findings: list[Finding]
    resolved_ids: list[str] = Field(default_factory=list)
    still_open: list[Finding] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    unlisted: int = 0
    unavailable: list[str] = Field(default_factory=list)


class PublishInput(BaseModel):
    pr: PrRef
    pr_base_sha: str
    head_sha: str
    workflow_id: str
    content: ReviewContent
    inline: bool = True


class ResolveInput(BaseModel):
    pr: PrRef
    finding_ids: list[str]


class RecoveryInput(BaseModel):
    pr: PrRef
    workflow_id: str


class RecoveredCounters(BaseModel):
    """The numbers an earlier run of the same workflow ID left on the pull request; 0 (or absent) when it left none."""

    last_round: int
    last_finding_numbers: dict[Category, int]
    last_fix_number: int


class CommentInput(BaseModel):
    """A comment in the pull request's Conversation."""

    pr: PrRef
    body: str
    marker: str  # idempotence: nothing is posted when a comment of the Conversation already carries it


class ThreadInput(BaseModel):
    pr: PrRef
    thread_root_id: int


class ThreadRead(BaseModel):
    comments: list[ThreadComment]  # the finding first, then the replies in order
    bot_login: str  # "<app slug>[bot]": tells the bot's replies from the humans'


class ThreadReplyInput(BaseModel):
    pr: PrRef
    thread_root_id: int
    body: str
    marker: str  # idempotence: nothing is posted when a comment of the pull request already carries it


class CommitInput(BaseModel):
    pr: PrRef
    workflow_id: str
    fix_number: int
    expected_head_sha: str
    plan: FixPlan


class CommitResult(BaseModel):
    sha: str
    rejected: list[str] = Field(default_factory=list)


class PullRequestOutcome(BaseModel):
    merged: bool
    closed_by: str | None
    open_findings: list[Finding]
    rounds: int
    closed_for_inactivity: bool = False  # closed by the workflow itself: closed_by is then None
