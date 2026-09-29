"""Secret shapes, written by `make github` / `make secrets` and read by the router and the worker."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

GITHUB_APP_SECRET = "code-review-agentcore-temporal/github-app"

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class GitHubAppSecret(BaseModel):
    """Written by `make github` from the manifest conversion; it also refreshes the slug after a rename."""

    app_id: int
    slug: NonEmpty
    client_id: NonEmpty
    private_key: NonEmpty
    webhook_secret: NonEmpty


class TemporalCertSecret(BaseModel):
    """mTLS client certificate and key, both PEM."""

    cert: NonEmpty
    key: NonEmpty
