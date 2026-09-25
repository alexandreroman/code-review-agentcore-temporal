"""Deterministic identifiers shared by the router and the worker."""


def _norm(value: str) -> str:
    return value.strip().lower()


def pr_workflow_id(owner: str, repo: str, number: int) -> str:
    return f"pr-{_norm(owner)}-{_norm(repo)}-{number}"


def reviewer_workflow_id(pr_id: str, round_number: int, category: str, batch: int | None = None) -> str:
    suffix = f"-b{batch}" if batch is not None else ""
    return f"{pr_id}-r{round_number}-{category}{suffix}"


def synthesis_workflow_id(pr_id: str, round_number: int) -> str:
    return f"{pr_id}-r{round_number}-synthesis"


def fixer_workflow_id(pr_id: str, fix_number: int) -> str:
    return f"{pr_id}-fix{fix_number}"


def snapshot_prefix(owner: str, repo: str, number: int) -> str:
    return f"{_norm(owner)}/{_norm(repo)}/pr-{number}/"


def snapshot_key(owner: str, repo: str, number: int, sha: str) -> str:
    return f"{snapshot_prefix(owner, repo, number)}{sha}.tar.gz"
