"""The worker's GitHub App client: one per process, built on first use from Secrets Manager.

Installation tokens are cached in process memory by GitHubApp; no secret reaches the Temporal history.
"""

from agentcore_review_shared.github import GitHubApp
from agentcore_review_shared.secrets import GitHubAppSecret

from .aws import read_secret

_secret_id: str | None = None
_app: GitHubApp | None = None


def configure(secret_id: str) -> None:
    """Called once when the worker registers its activities."""
    global _secret_id, _app
    _secret_id, _app = secret_id, None


def github() -> GitHubApp:
    global _app
    if _app is None:
        if _secret_id is None:
            raise RuntimeError("github_client.configure() was not called")
        secret = GitHubAppSecret.model_validate_json(read_secret(_secret_id))
        _app = GitHubApp(secret.client_id, secret.private_key)
    return _app
