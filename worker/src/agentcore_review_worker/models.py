"""Worker-internal models passed between the pull request workflow, its children and the activities.

The parent workflow only handles metadata (paths, SHAs, snapshot references): patches and file
contents appear only in the reviewer and fixer children.
"""

from typing import Literal

from agentcore_review_shared.contract import Category, Finding, FixPlan, PrRef
from pydantic import BaseModel, Field

MODEL_NAME = "claude"
"""Name of the single model factory registered in StrandsPlugin and used by every TemporalAgent."""


class ChangedFile(BaseModel):
    path: str
    status: str
    additions: int
    deletions: int
    patch_bytes: int | None


class ChangeSet(BaseModel):
    head_sha: str
    base_sha: str
    diff_base: str | None = None  # None: the whole pull request; otherwise the last reviewed SHA
    files: list[ChangedFile] = Field(default_factory=list)  # reviewable files only
    excluded: list[str] = Field(default_factory=list)
    # A worker setting carried to workflow code, which cannot read the environment.
    max_parallel_agents: int = 3


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
    diff_base: str | None
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


class SynthesisInput(BaseModel):
    new_findings: list[Finding]
    still_open: list[Finding] = Field(default_factory=list)
    resolved_ids: list[str] = Field(default_factory=list)
    unavailable: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)


class FixerInput(BaseModel):
    pr: PrRef
    workflow_id: str
    fix_number: int
    expected_head_sha: str
    snapshot: SnapshotRef
    findings: list[Finding]


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
    unavailable: list[str] = Field(default_factory=list)


class PublishInput(BaseModel):
    pr: PrRef
    head_sha: str
    workflow_id: str
    content: ReviewContent
    inline: bool = True


class PublishResult(BaseModel):
    review_id: int
    comment_ids: dict[str, int] = Field(default_factory=dict)


class ResolveInput(BaseModel):
    pr: PrRef
    finding_ids: list[str]


class ClosingInput(BaseModel):
    pr: PrRef
    workflow_id: str
    body: str


class CommitInput(BaseModel):
    pr: PrRef
    workflow_id: str
    fix_number: int
    expected_head_sha: str
    plan: FixPlan


class CommitResult(BaseModel):
    sha: str
    rejected: list[str] = Field(default_factory=list)
