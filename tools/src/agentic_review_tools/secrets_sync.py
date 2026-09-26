"""Pushes the Anthropic key and the Temporal mTLS certificates from .env to Secrets Manager (make secrets)."""

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path

from agentic_review_shared.secrets import (
    ANTHROPIC_SECRET,
    ROUTER_CERT_SECRET,
    WORKER_CERT_SECRET,
    AnthropicSecret,
    TemporalCertSecret,
)
from botocore.exceptions import ClientError
from pydantic import BaseModel


class ConfigError(Exception):
    """A setting from .env is missing or invalid."""


def desired_secrets(env: Mapping[str, str]) -> dict[str, BaseModel]:
    """Every secret value to push. Validates everything before anything is written."""
    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise ConfigError("ANTHROPIC_API_KEY is empty in .env")
    return {
        ANTHROPIC_SECRET: AnthropicSecret(api_key=api_key),
        WORKER_CERT_SECRET: _certificate(env, "WORKER"),
        ROUTER_CERT_SECRET: _certificate(env, "ROUTER"),
    }


def sync_secret(client, secret_id: str, value: BaseModel) -> str:
    """Write the value unless the secret already holds the same JSON; returns "updated" or "unchanged"."""
    desired = value.model_dump_json()
    try:
        current = client.get_secret_value(SecretId=secret_id)["SecretString"]
    except ClientError as error:
        if error.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        current = None
    if current is not None and _same_json(current, desired):
        return "unchanged"
    client.put_secret_value(SecretId=secret_id, SecretString=desired)
    return "updated"


def _certificate(env: Mapping[str, str], component: str) -> TemporalCertSecret:
    return TemporalCertSecret(
        cert=_read_pem(env, f"TEMPORAL_{component}_CERT_PATH"),
        key=_read_pem(env, f"TEMPORAL_{component}_KEY_PATH"),
    )


def _read_pem(env: Mapping[str, str], name: str) -> str:
    path = env.get(name, "").strip()
    if not path:
        raise ConfigError(f"{name} is not set")
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        raise ConfigError(f"{path} not found ({name})") from None
    except OSError as error:
        raise ConfigError(f"{path} cannot be read ({name}): {error.strerror or error}") from None
    if "-----BEGIN " not in text:
        raise ConfigError(f"{path} is not a PEM file ({name})")
    return text


def _same_json(left: str, right: str) -> bool:
    try:
        return json.loads(left) == json.loads(right)
    except ValueError:
        return False


def main() -> None:
    import boto3

    try:
        wanted = desired_secrets(os.environ)
        client = boto3.client("secretsmanager")
        for secret_id, value in wanted.items():
            print(f"{secret_id}: {sync_secret(client, secret_id, value)}")
    except ConfigError as error:
        sys.exit(f"make secrets: {error}")
    except ClientError as error:
        sys.exit(f"make secrets: {error} (has make infra run?)")


if __name__ == "__main__":
    main()
