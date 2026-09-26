from temporalio import activity


class PingActivities:
    def __init__(self, identity: str) -> None:
        self._identity = identity

    @activity.defn(name="ping")
    async def ping(self, message: str) -> str:
        return f"pong: {message} (worker {self._identity})"
