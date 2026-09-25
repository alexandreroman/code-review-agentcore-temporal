"""Worker identities. The AgentCore session ID lives in the identity so /kill can target it."""

from dataclasses import dataclass

AGENTCORE_PREFIX = "agentcore"
DEV_PREFIX = "dev"


@dataclass(frozen=True)
class AgentCoreSession:
    endpoint: str
    session_id: str


def agentcore_identity(endpoint: str, session_id: str) -> str:
    if not endpoint or ":" in endpoint:
        raise ValueError(f"invalid endpoint name: {endpoint!r}")
    if not session_id:
        raise ValueError("empty session id")
    return f"{AGENTCORE_PREFIX}:{endpoint}:{session_id}"


def dev_identity(hostname: str) -> str:
    return f"{DEV_PREFIX}:{hostname}"


def parse_agentcore_identity(identity: str) -> AgentCoreSession | None:
    parts = identity.split(":", 2)
    if len(parts) != 3 or parts[0] != AGENTCORE_PREFIX or not parts[1] or not parts[2]:
        return None
    return AgentCoreSession(endpoint=parts[1], session_id=parts[2])
