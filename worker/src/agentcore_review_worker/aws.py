"""AWS clients for the worker, created once per process."""

from functools import cache

import boto3


@cache
def s3():
    return boto3.client("s3")


@cache
def _secrets_manager():
    return boto3.client("secretsmanager")


@cache
def _agentcore_identity():
    return boto3.client("bedrock-agentcore")


def read_secret(secret_id: str) -> str:
    """A secret's string value, by ARN (AgentCore) or name (dev worker)."""
    return _secrets_manager().get_secret_value(SecretId=secret_id)["SecretString"]


def read_api_key(workload_identity: str, credential_provider: str) -> str:
    """An API key from an AgentCore Identity credential provider, fetched as the given workload identity.

    The worker mints its own workload access token, the same way on AgentCore and in the dev worker: the runtime
    gives none to a session started without a user ID, as Temporal starts them, and the runtime's own workload
    identity cannot mint one.
    """
    identity = _agentcore_identity()
    token = identity.get_workload_access_token(workloadName=workload_identity)["workloadAccessToken"]
    response = identity.get_resource_api_key(
        workloadIdentityToken=token, resourceCredentialProviderName=credential_provider
    )
    return response["apiKey"]
