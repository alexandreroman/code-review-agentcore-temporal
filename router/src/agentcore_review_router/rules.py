"""Pure command rules: who may run /fix and /kill, which threads are findings, which sessions /kill targets, and
what the bot answers."""

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from agentcore_review_shared.contract import AgentCoreSession, parse_agentcore_identity

# The permission endpoint answers admin, write, read or none; maintain is a role that maps to write.
WRITE_PERMISSIONS = frozenset({"admin", "write"})

REACTION_DENIED = "confused"  # 😕
REACTION_FIX = "eyes"  # 👀
REACTION_KILL = "rocket"  # GitHub has no 💥 reaction: the /kill comment carries it

NO_REVIEW_REPLY = "No review in progress."
DEV_KILL_REPLY = "Dev worker: Ctrl-C is your friend."
NO_WORKER_REPLY = "No active worker, nothing to kill."

StopOutcome = Literal["stopped", "gone", "retry", "failed"]
# 409 while a session changes state, throttling, and connect or read timeouts ("timeout") are worth another try.
RETRYABLE_STOP_ERRORS = frozenset({"ConflictException", "ThrottlingException", "timeout"})


def can_run_commands(permission: str | None) -> bool:
    """author_association is not enough (MEMBER does not grant write): the collaborator permission decides."""
    return permission in WRITE_PERMISSIONS


def is_bot_login(login: str | None, bot_login: str) -> bool:
    """The GitHub App comments as "<app slug>[bot]"; a human may pick the bare slug as a user name."""
    return login == bot_login


def kill_targets(identities: Iterable[str]) -> list[AgentCoreSession]:
    """AgentCore sessions among the pollers, once each: a worker polls both workflow and activity tasks."""
    sessions = {session for session in map(parse_agentcore_identity, identities) if session is not None}
    return sorted(sessions, key=lambda session: (session.endpoint, session.session_id))


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
