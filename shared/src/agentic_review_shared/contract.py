"""Signals, queries and models exchanged between the router, the workflows and the agents."""

from enum import StrEnum

from pydantic import BaseModel, Field

SIGNAL_PR_UPDATED = "pr_updated"
SIGNAL_FIX_REQUESTED = "fix_requested"
SIGNAL_PR_CLOSED = "pr_closed"
QUERY_GET_FINDINGS = "get_findings"
CHECK_NAME = "AI Review"


class Category(StrEnum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class Severity(StrEnum):
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


class PrRef(BaseModel):
    owner: str
    repo: str
    number: int
    installation_id: int


class PrUpdated(BaseModel):
    head_sha: str
    delivery_id: str


class FixRequested(BaseModel):
    requested_by: str
    delivery_id: str


class PrClosed(BaseModel):
    merged: bool
    closed_by: str | None
    delivery_id: str


class FindingDraft(BaseModel):
    category: Category
    severity: Severity
    path: str
    line: int = Field(ge=1)
    end_line: int | None = Field(default=None, ge=1)
    title: str
    explanation: str
    suggestion: str | None = None


class Finding(FindingDraft):
    id: str
    comment_id: int | None = None


class ReviewerReport(BaseModel):
    findings: list[FindingDraft] = Field(default_factory=list)
    resolved_ids: list[str] = Field(default_factory=list)


class ReviewSummary(BaseModel):
    summary_markdown: str
    ordered_ids: list[str]
    duplicates: list[str] = Field(default_factory=list)


class FileChange(BaseModel):
    path: str
    new_content: str


class FixPlan(BaseModel):
    changes: list[FileChange]
    commit_message: str


class PullRequestState(BaseModel):
    last_reviewed_sha: str | None = None
    pending_head_sha: str | None = None
    pending_fix: FixRequested | None = None
    open_findings: list[Finding] = Field(default_factory=list)
    round: int = 0
    fix_count: int = 0
    next_finding_number: int = 1
    check_run_id: int | None = None


class PullRequestInput(BaseModel):
    pr: PrRef
    state: PullRequestState = Field(default_factory=PullRequestState)


class PullRequestOutcome(BaseModel):
    merged: bool
    closed_by: str | None
    open_findings: list[Finding]
    rounds: int
