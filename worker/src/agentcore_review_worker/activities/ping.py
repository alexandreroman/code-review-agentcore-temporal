from temporalio import activity

from .heartbeats import heartbeat_while_running


class PingActivities:
    def __init__(self, identity: str) -> None:
        self._identity = identity

    @activity.defn(name="Ping")
    @heartbeat_while_running
    async def ping(self, message: str) -> str:
        return f"pong: {message} (worker {self._identity})"
