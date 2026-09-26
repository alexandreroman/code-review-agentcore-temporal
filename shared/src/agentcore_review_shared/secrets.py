"""Secrets Manager names and payloads, shared by the tools that write them and the code that reads them."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

SECRET_PREFIX = "temporal-agentcore-review-demo"
GITHUB_APP_SECRET = f"{SECRET_PREFIX}/github-app"
ANTHROPIC_SECRET = f"{SECRET_PREFIX}/anthropic-api-key"
WORKER_CERT_SECRET = f"{SECRET_PREFIX}/temporal-worker-cert"
ROUTER_CERT_SECRET = f"{SECRET_PREFIX}/temporal-router-cert"

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class GitHubAppSecret(BaseModel):
    """Written by `make github-app` from the manifest conversion."""

    app_id: int
    slug: NonEmpty
    client_id: NonEmpty
    private_key: NonEmpty
    webhook_secret: NonEmpty
    html_url: NonEmpty


class AnthropicSecret(BaseModel):
    api_key: NonEmpty


class TemporalCertSecret(BaseModel):
    """mTLS client certificate and key, both PEM."""

    cert: NonEmpty
    key: NonEmpty
