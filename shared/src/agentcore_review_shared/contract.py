"""Identifiers, signals and models exchanged between the router and the worker."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

SIGNAL_PR_UPDATED = "pr_updated"
SIGNAL_FIX_REQUESTED = "fix_requested"
SIGNAL_COMMENT_POSTED = "comment_posted"
SIGNAL_PR_CLOSED = "pr_closed"
PULL_REQUEST_WORKFLOW = "PullRequestWorkflow"


def pr_workflow_id(owner: str, repo: str, number: int) -> str:
    # GitHub events may spell the owner and repository with different cases.
    return f"pr-{owner.lower()}-{repo.lower()}-{number}"


@dataclass(frozen=True)
class AgentCoreSession:
    endpoint: str
    session_id: str


def agentcore_identity(endpoint: str, session_id: str) -> str:
    """Worker identity on AgentCore: the session ID lives in the identity so /kill can target it."""
    return f"agentcore:{endpoint}:{session_id}"


def parse_agentcore_identity(identity: str) -> AgentCoreSession | None:
    parts = identity.split(":", 2)
    if len(parts) != 3 or parts[0] != "agentcore" or not parts[1] or not parts[2]:
        return None
    return AgentCoreSession(endpoint=parts[1], session_id=parts[2])


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
    # The first comment of the review thread /fix was posted in; None in the Conversation.
    thread_root_id: int | None = None
    # The finding IDs after /fix, empty for a bare /fix: the thread's finding, or every open finding in the
    # Conversation.
    finding_ids: list[str] = Field(default_factory=list)


class CommentPosted(BaseModel):
    """A plain reply in a finding's review thread; the worker reads the thread itself, so the body stays out."""

    comment_id: int
    thread_root_id: int
    author: str
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


class DismissedFinding(BaseModel):
    finding: Finding
    reason: str
    dismissed_by: str


class PullRequestState(BaseModel):
    last_reviewed_sha: str | None = None
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
    next_finding_number: int = 1


class PullRequestInput(BaseModel):
    pr: PrRef
    state: PullRequestState = Field(default_factory=PullRequestState)
