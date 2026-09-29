"""AWS clients for the worker, created once per process."""

from functools import cache

import boto3
from botocore.config import Config

# An S3 call gives up inside its activity attempt, which Temporal then retries: 2 × (3 + 10) s = 26 s at worst, under
# every S3 activity's start-to-close.
S3_CONFIG = Config(connect_timeout=3, read_timeout=10, retries={"total_max_attempts": 2})


@cache
def s3():
    return boto3.client("s3", config=S3_CONFIG)


@cache
def _secrets_manager():
    return boto3.client("secretsmanager")


def read_secret(secret_id: str) -> str:
    """A secret's string value, by ARN (AgentCore) or name (dev worker)."""
    return _secrets_manager().get_secret_value(SecretId=secret_id)["SecretString"]
