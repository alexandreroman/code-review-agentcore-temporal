"""Secrets Manager names and payloads, shared by the tools that write them and the code that reads them."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

GITHUB_APP_SECRET = "temporal-agentcore-review-demo/github-app"
ANTHROPIC_SECRET = "temporal-agentcore-review-demo/anthropic-api-key"

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class GitHubAppSecret(BaseModel):
    """Written by `make github-app` from the manifest conversion."""

    app_id: int
    slug: NonEmpty
    client_id: NonEmpty
    private_key: NonEmpty
    webhook_secret: NonEmpty


class AnthropicSecret(BaseModel):
    api_key: NonEmpty


class TemporalCertSecret(BaseModel):
    """mTLS client certificate and key, both PEM."""

    cert: NonEmpty
    key: NonEmpty
