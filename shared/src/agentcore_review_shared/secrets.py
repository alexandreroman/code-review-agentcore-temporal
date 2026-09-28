"""Where secrets live and what they hold, shared by the tools that write them and the code that reads them."""

from typing import Annotated

from pydantic import BaseModel, StringConstraints

GITHUB_APP_SECRET = "code-review-agentcore-temporal/github-app"

# The worker reads the Anthropic API key through AgentCore Identity, as its own workload identity, from an API key
# credential provider backed by the Secrets Manager secret that make secrets fills (infra/aws/secrets.tf).
WORKER_WORKLOAD_IDENTITY = "code-review-agentcore-temporal-worker"
ANTHROPIC_CREDENTIAL_PROVIDER = "agentcore-review-demo-anthropic"

NonEmpty = Annotated[str, StringConstraints(min_length=1)]


class GitHubAppSecret(BaseModel):
    """Written by `make github-app` from the manifest conversion; `make github` refreshes the slug after a rename."""

    app_id: int
    slug: NonEmpty
    client_id: NonEmpty
    private_key: NonEmpty
    webhook_secret: NonEmpty


class TemporalCertSecret(BaseModel):
    """mTLS client certificate and key, both PEM."""

    cert: NonEmpty
    key: NonEmpty
