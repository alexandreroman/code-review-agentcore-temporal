"""Runs the external CLIs the tools drive (tofu, temporal, aws, podman, git)."""

import os
import subprocess
from collections.abc import Mapping, Sequence


class Shell:
    """Real commands. Tests use a fake with the same two methods."""

    def capture(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        stdin: str | None = None,
        quiet: bool = False,
    ) -> str:
        """Run a command and return its stdout. stderr goes to the terminal unless `quiet`."""
        return subprocess.run(
            list(args),
            env=_merged(env),
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL if quiet else None,
            text=True,
            check=True,
        ).stdout

    def stream(self, args: Sequence[str], *, env: Mapping[str, str] | None = None, stdin: str | None = None) -> None:
        """Run a command whose output goes straight to the terminal (and whose prompts reach the user)."""
        subprocess.run(list(args), env=_merged(env), input=stdin, text=True, check=True)


def _merged(env: Mapping[str, str] | None) -> dict[str, str] | None:
    return None if env is None else {**os.environ, **env}
