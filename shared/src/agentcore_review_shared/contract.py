"""What crosses the router/worker boundary: workflow and signal names, IDs, workflow input and signal payloads."""

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field

SIGNAL_PR_UPDATED = "pr_updated"
SIGNAL_FIX_REQUESTED = "fix_requested"
SIGNAL_COMMENT_POSTED = "comment_posted"
SIGNAL_PR_CLOSED = "pr_closed"
PULL_REQUEST_WORKFLOW = "PullRequestWorkflow"
REVIEWER_WORKFLOW = "ReviewerWorkflow"
FIXER_WORKFLOW = "FixerWorkflow"
SYNTHESIS_WORKFLOW = "SynthesisWorkflow"
DISCUSSION_WORKFLOW = "DiscussionWorkflow"


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


class LenientEnum(StrEnum):
    """Accepts case and spacing variations ("Security", " HIGH "), which agents' structured output produces."""

    @classmethod
    def _missing_(cls, value: object) -> LenientEnum | None:
        if isinstance(value, str):
            wanted = value.strip().lower()
            for member in cls:
                if member.value == wanted:
                    return member
        return None


class Category(LenientEnum):
    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"

    @property
    def prefix(self) -> str:
        """The letter that starts the IDs of this category's findings: S-01, P-01, M-01."""
        return self.value[0].upper()


_CATEGORY_BY_PREFIX = {category.prefix: category for category in Category}

# ASCII digits only: \d would also accept other scripts' digits, which no finding ID contains.
FINDING_ID_PATTERN = "[" + "".join(_CATEGORY_BY_PREFIX) + "]-[0-9]+"
_FINDING_ID = re.compile(FINDING_ID_PATTERN)


def format_finding_id(category: Category, number: int) -> str:
    """S-01 for the first security finding; at least two digits, so the hundredth is S-100."""
    return f"{category.prefix}-{number:02d}"


def parse_finding_id(text: str) -> tuple[Category, int] | None:
    """The category and number of a finding ID (S-01 gives security and 1); None when the text is not one."""
    if not _FINDING_ID.fullmatch(text):
        return None
    prefix, _, number = text.partition("-")
    return _CATEGORY_BY_PREFIX[prefix], int(number)


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


class PullRequestInput(BaseModel):
    """What the router starts a pull request workflow with; the worker adds the state a continue-as-new carries."""

    pr: PrRef
    # Seconds without activity before the warning comment, then before the pull request is closed.
    idle_warning_seconds: int
    idle_close_seconds: int
    # The run was started by a reopen: the bot announces the new review.
    reopened: bool = False
