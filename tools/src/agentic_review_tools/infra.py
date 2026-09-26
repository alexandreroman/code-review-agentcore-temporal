"""Applies the aws stack while keeping every AgentCore endpoint a pinned workflow may still need.

The endpoints to keep live only in the stack outputs, so every apply goes through here: it re-reads them and
passes them back as variables. If the outputs cannot be read, nothing is applied.
"""

import argparse
import json
import subprocess
import sys
from collections.abc import Collection

from .shell import Shell

AWS_STACK = "infra/aws"


def read_outputs(shell, stack: str = AWS_STACK) -> dict:
    return json.loads(shell.capture(["tofu", f"-chdir={stack}", "output", "-json"]) or "{}")


def output(outputs: dict, name: str, default=""):
    return (outputs.get(name) or {}).get("value", default) or default


def stack_vars(outputs: dict, build_id: str | None = None, drop: Collection[str] = ()) -> dict[str, str]:
    current = output(outputs, "current_build")
    build = build_id or current
    if build and build in drop:
        raise ValueError(f"cannot drop the current build {build}")
    endpoints = output(outputs, "endpoints", {})
    retained = {name: e["version"] for name, e in endpoints.items() if name != build and name not in drop}
    return {"TF_VAR_build_id": build, "TF_VAR_retained_endpoints": json.dumps(retained, sort_keys=True)}


def apply(shell, build_id: str | None = None, drop: Collection[str] = ()) -> None:
    variables = stack_vars(read_outputs(shell), build_id, drop)
    shell.stream(["tofu", f"-chdir={AWS_STACK}", "apply", "-input=false", "-auto-approve"], env=variables)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agentic_review_tools.infra")
    commands = parser.add_subparsers(dest="command", required=True)
    apply_parser = commands.add_parser("apply", help="apply the aws stack, keeping the deployed endpoints")
    apply_parser.add_argument("--build-id")
    apply_parser.add_argument("--drop", nargs="*", default=[])
    args = parser.parse_args(argv)
    try:
        apply(Shell(), args.build_id, args.drop)
    except subprocess.CalledProcessError as error:
        sys.exit(f"make infra: {' '.join(error.cmd)} failed")


if __name__ == "__main__":
    main()
