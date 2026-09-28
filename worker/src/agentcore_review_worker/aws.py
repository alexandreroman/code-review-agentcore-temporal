"""AWS clients for the worker, created once per process."""

from functools import cache

import boto3


@cache
def s3():
    return boto3.client("s3")


@cache
def _secrets_manager():
    return boto3.client("secretsmanager")


def read_secret(secret_id: str) -> str:
    """A secret's string value, by ARN (AgentCore) or name (dev worker)."""
    return _secrets_manager().get_secret_value(SecretId=secret_id)["SecretString"]
