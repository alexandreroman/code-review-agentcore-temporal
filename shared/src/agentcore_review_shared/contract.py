"""Signals, queries and models exchanged between the router, the workflows and the agents."""

from enum import StrEnum

from pydantic import BaseModel, Field

SIGNAL_PR_UPDATED = "pr_updated"
SIGNAL_FIX_REQUESTED = "fix_requested"
SIGNAL_PR_CLOSED = "pr_closed"
PULL_REQUEST_WORKFLOW = "PullRequestWorkflow"
QUERY_GET_FINDINGS = "get_findings"
CHECK_NAME = "AI Review"


class _LenientEnum(StrEnum):
    """Accepts case and spacing variations ("Security", " HIGH "), which agents' structured output produces."""

    @classmethod
    def _missing_(cls, value: object) -> _LenientEnum | None:
        if isinstance(value, str):
            wanted = value.strip().lower()
            for member in cls:
                if member.value == wanted:
                    return member
        return None


class Category(_LenientEnum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


class Severity(_LenientEnum):
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


class PullRequestState(BaseModel):
    last_reviewed_sha: str | None = None
    pending_head_sha: str | None = None
    pending_fix: FixRequested | None = None
    # Delivery IDs of the latest fix requests: GitHub redelivers webhooks, and a repeat must not fix twice.
    fix_deliveries: list[str] = Field(default_factory=list)
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
