"""AWS clients for the worker, created on first use: importing this module never loads boto3.

The navigation tools are imported by workflow modules (to wrap them as agent tools), so everything
they reach must keep I/O libraries out of module-level imports.
"""

from functools import cache


@cache
def s3():
    import boto3

    return boto3.client("s3")


@cache
def _secrets_manager():
    import boto3

    return boto3.client("secretsmanager")


def read_secret(secret_id: str) -> str:
    """A secret's string value, by ARN (AgentCore) or name (dev worker)."""
    return _secrets_manager().get_secret_value(SecretId=secret_id)["SecretString"]
