"""Pure command rules: who may run /fix and /kill, which findings /fix names, which sessions /kill targets, and
what the bot answers."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from agentcore_review_shared.contract import (
    AgentCoreSession,
    format_finding_id,
    parse_agentcore_identity,
    parse_finding_id,
)

# The permission endpoint reports the maintain role as write.
WRITE_PERMISSIONS = frozenset({"admin", "write"})

REACTION_DENIED = "confused"  # 😕
REACTION_ACK = "eyes"  # 👀 acknowledges a /fix, a forwarded reply or a mention of the bot
REACTION_KILL = "rocket"  # GitHub has no 💥 reaction: the /kill comment carries it

NO_REVIEW_REPLY = "No review in progress."
DEV_KILL_REPLY = "Dev worker: Ctrl-C is your friend."
NO_WORKER_REPLY = "No active worker, nothing to kill."
FIX_USAGE_REPLY = (
    "Nothing was fixed: `/fix` accepts finding IDs only, such as `/fix S-01 P-02`. "
    "A bare `/fix` fixes every open finding, or the thread's finding in a review thread."
)

StopOutcome = Literal["stopped", "gone", "retry", "failed"]
# 409 while a session changes state, throttling, and connect or read timeouts ("timeout") are worth another try.
RETRYABLE_STOP_ERRORS = frozenset({"ConflictException", "ThrottlingException", "timeout"})


def can_run_commands(permission: str | None) -> bool:
    """author_association is not enough (MEMBER does not grant write): the collaborator permission decides."""
    return permission in WRITE_PERMISSIONS


def fix_finding_ids(arguments: Iterable[str]) -> list[str] | None:
    """The finding IDs named after /fix, written as the worker writes them (s-1 gives S-01) and once each; None when
    an argument is not a finding ID.

    Only the syntax is checked here: the worker alone knows which findings are open.
    """
    finding_ids: list[str] = []
    for argument in arguments:
        parsed = parse_finding_id(argument.upper())
        if parsed is None:
            return None
        category, number = parsed
        finding_ids.append(format_finding_id(category, number))
    return list(dict.fromkeys(finding_ids))


def kill_targets(identities: Iterable[str]) -> list[AgentCoreSession]:
    """AgentCore sessions among the pollers, once each in first-seen order: a worker polls two task types."""
    sessions = [parse_agentcore_identity(identity) for identity in identities]
    return list(dict.fromkeys(session for session in sessions if session is not None))


def stop_outcome(error_code: str | None) -> StopOutcome:
    """Classify a StopRuntimeSession result from its error code (None when the call succeeded)."""
    if error_code is None:
        return "stopped"
    if error_code == "ResourceNotFoundException":
        return "gone"  # the poller list keeps sessions seen in the last ~5 minutes, dead ones included
    if error_code in RETRYABLE_STOP_ERRORS:
        return "retry"
    return "failed"


@dataclass(frozen=True)
class KillTally:
    stopped: int = 0
    gone: int = 0
    failed: int = 0

    def add(self, outcomes: Iterable[StopOutcome]) -> KillTally:
        """Stops still unconfirmed ("retry") count as failed."""
        counts = Counter(outcomes)
        return KillTally(
            stopped=self.stopped + counts["stopped"],
            gone=self.gone + counts["gone"],
            failed=self.failed + counts["failed"] + counts["retry"],
        )


def kill_comment(tally: KillTally) -> str:
    noun = "session" if tally.stopped == 1 else "sessions"
    parts = [f"💥 {tally.stopped} AgentCore {noun} stopped"]
    if tally.gone:
        parts.append(f"{tally.gone} already gone")
    if tally.failed:
        parts.append(f"{tally.failed} failed (see the router logs)")
    return ", ".join(parts) + "."
