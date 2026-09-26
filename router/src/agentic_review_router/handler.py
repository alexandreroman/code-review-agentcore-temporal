"""Lambda entry point behind the Function URL. This version only checks the webhook signature and acknowledges."""

import logging
import os
from functools import cache

from agentic_review_shared.secrets import GitHubAppSecret

from .signature import decode_body, verify_signature

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def handle(event: dict, secret: str) -> dict:
    headers = {name.lower(): value for name, value in (event.get("headers") or {}).items()}
    valid = verify_signature(secret, decode_body(event), headers.get("x-hub-signature-256"))
    status = 204 if valid else 401
    logger.info(
        "webhook",
        extra={
            "delivery": headers.get("x-github-delivery", ""),
            "event": headers.get("x-github-event", ""),
            "status": status,
        },
    )
    return {"statusCode": status}


@cache
def _webhook_secret() -> str:
    """Read once per warm Lambda; a failure is not cached, so the next call retries."""
    import boto3

    value = boto3.client("secretsmanager").get_secret_value(SecretId=os.environ["GITHUB_APP_SECRET_ARN"])
    return GitHubAppSecret.model_validate_json(value["SecretString"]).webhook_secret


def handler(event: dict, context: object) -> dict:
    try:
        secret = _webhook_secret()
    except Exception:
        logger.exception("GitHub App secret unavailable (has make github-app run?)")
        return {"statusCode": 503}
    return handle(event, secret)
