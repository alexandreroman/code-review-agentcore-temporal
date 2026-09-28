"""Worker-internal models passed between the pull request workflow, its children and the activities.

The parent workflow only handles metadata (paths, SHAs, snapshot references): patches and file
contents appear only in the reviewer and fixer children.
"""

from typing import Literal

from agentcore_review_shared.contract import Category, DismissedFinding, Finding, FindingDraft, PrRef
from pydantic import BaseModel, Field

# Here rather than in agent_model so that workflow code can import it without agent_model's I/O libraries.
MODEL_NAME = "claude"
"""Name of the single model factory registered in StrandsPlugin and used by every TemporalAgent."""


class ChangedFile(BaseModel):
    path: str
    patch_bytes: int | None


class ChangeSet(BaseModel):
    head_sha: str
    diff_base: str  # the last reviewed SHA for a delta, the base branch's SHA for the whole pull request
    files: list[ChangedFile] = Field(default_factory=list)  # reviewable files only
    excluded: list[str] = Field(default_factory=list)
    unlisted: int = 0  # changed files beyond the ones a GitHub comparison lists
    # A worker setting carried to workflow code, which cannot read the environment.
    max_parallel_agents: int


class ListFilesInput(BaseModel):
    pr: PrRef
    since_sha: str | None = None


class SnapshotInput(BaseModel):
    pr: PrRef
    sha: str


class SnapshotRef(BaseModel):
    owner: str
    repo: str
    installation_id: int
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
    changes: list[FileChange]
    commit_message: str = Field(
        description="Imperative subject of at most 50 characters, a blank line, then one line per fixed finding"
    )


class DiscussionReply(BaseModel):
    verdict: Literal["keep", "dismiss"] = Field(
        description="dismiss only when the code shows the finding is wrong or does not apply"
    )
    answer: str = Field(description="Markdown answer to the human, about 150 words at most")


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
    head_sha: str
    workflow_id: str
    content: ReviewContent
    inline: bool = True


class ResolveInput(BaseModel):
    pr: PrRef
    finding_ids: list[str]


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
