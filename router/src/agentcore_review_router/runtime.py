"""Per-container runtime: settings, one event loop, and the clients reused while the Lambda stays warm.

Every invocation runs on the same asyncio.Runner loop, which is never closed. The Temporal client and the GitHub
App's httpx client are bound to that loop, so reusing them across invocations is safe; asyncio.run would give each
invocation a new loop and leave them bound to a closed one. A failed creation is not cached: the next call retries.
"""

import asyncio
import os
import time
from collections.abc import Coroutine
from dataclasses import dataclass
from functools import cache
from typing import Any

import boto3
from agentcore_review_shared.github import GitHubApp
from agentcore_review_shared.secrets import GITHUB_APP_SECRET, GitHubAppSecret, TemporalCertSecret
from botocore.config import Config
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.service import TLSConfig

from .routing import RouterConfig
from .tracing import XRayTraceInterceptor

IDENTITY = "agentcore-review-demo-router"
GITHUB_TIMEOUT = 5.0
# /kill must fit in the webhook's 10 s: short per-call timeouts, no SDK retry (sessions.py retries transient errors).
STOP_CALL_CONFIG = Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1, "mode": "standard"})
# The Lambda self-invoke must fit in the webhook's 10 s too. No retry: a retried asynchronous invoke would run the
# /kill follow-up twice, and post its comment twice.
SHORT_CALL_CONFIG = Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1, "mode": "standard"})
# A secret read is idempotent: one retry, still within the webhook's 10 s.
SECRETS_CALL_CONFIG = Config(connect_timeout=2, read_timeout=2, retries={"total_max_attempts": 2})
# Seconds between two reads of the GitHub App secret triggered by a signature that does not match.
SECRET_REFRESH_INTERVAL = 60.0


@dataclass(frozen=True)
class Settings:
    temporal_address: str
    temporal_namespace: str
    task_queue: str
    dev_task_queue: str
    dev_branch_prefix: str
    pr_idle_warning_seconds: int
    pr_idle_close_seconds: int
    runtime_arn: str  # empty until the first make deploy
    temporal_cert_secret_arn: str
    function_name: str
    tracing: bool  # TRACING=on: the workflows join the invocation's X-Ray trace


_runner = asyncio.Runner()
_temporal: Client | None = None
_secret_refreshed_at: float | None = None  # time.monotonic() of the last refresh


def run[T](coro: Coroutine[Any, Any, T]) -> T:
    return _runner.run(coro)


@cache
def settings() -> Settings:
    env = os.environ
    return Settings(
        temporal_address=env["TEMPORAL_ADDRESS"],
        temporal_namespace=env["TEMPORAL_NAMESPACE"],
        task_queue=env["TASK_QUEUE"],
        dev_task_queue=env["DEV_TASK_QUEUE"],
        dev_branch_prefix=env["DEV_BRANCH_PREFIX"],
        pr_idle_warning_seconds=int(env["PR_IDLE_WARNING_SECONDS"]),
        pr_idle_close_seconds=int(env["PR_IDLE_CLOSE_SECONDS"]),
        runtime_arn=env.get("AGENTCORE_RUNTIME_ARN", ""),
        temporal_cert_secret_arn=env["TEMPORAL_CERT_SECRET_ARN"],
        function_name=env["AWS_LAMBDA_FUNCTION_NAME"],
        tracing=env.get("TRACING") == "on",
    )


@cache
def _secretsmanager() -> Any:
    return boto3.client("secretsmanager", config=SECRETS_CALL_CONFIG)


def _secret(secret_id: str) -> str:
    return _secretsmanager().get_secret_value(SecretId=secret_id)["SecretString"]


@cache
def github_app_secret() -> GitHubAppSecret:
    return GitHubAppSecret.model_validate_json(_secret(GITHUB_APP_SECRET))


def refresh_github_app_secret() -> bool:
    """Reads the secret again, at most once per SECRET_REFRESH_INTERVAL; False when throttled.

    The GitHub client, with its token cache, is rebuilt only when the credentials changed.
    """
    global _secret_refreshed_at
    now = time.monotonic()
    if _secret_refreshed_at is not None and now - _secret_refreshed_at < SECRET_REFRESH_INTERVAL:
        return False
    _secret_refreshed_at = now
    previous = github_app_secret()
    github_app_secret.cache_clear()
    current = github_app_secret()
    if current.client_id != previous.client_id or current.private_key != previous.private_key:
        github.cache_clear()
    return True


def router_config() -> RouterConfig:
    current = settings()
    return RouterConfig(
        prod_queue=current.task_queue,
        dev_queue=current.dev_task_queue,
        dev_branch_prefix=current.dev_branch_prefix,
        app_slug=github_app_secret().slug,
        idle_warning_seconds=current.pr_idle_warning_seconds,
        idle_close_seconds=current.pr_idle_close_seconds,
    )


async def temporal_client() -> Client:
    global _temporal
    if _temporal is None:
        current = settings()
        cert = TemporalCertSecret.model_validate_json(_secret(current.temporal_cert_secret_arn))
        _temporal = await Client.connect(
            current.temporal_address,
            namespace=current.temporal_namespace,
            tls=TLSConfig(client_cert=cert.cert.encode(), client_private_key=cert.key.encode()),
            data_converter=pydantic_data_converter,
            identity=IDENTITY,
            interceptors=[XRayTraceInterceptor()] if current.tracing else [],
        )
    return _temporal


@cache
def github() -> GitHubApp:
    """Keeps the installation token cache for the life of the container."""
    app = github_app_secret()
    return GitHubApp(app.client_id, app.private_key, timeout=GITHUB_TIMEOUT)


@cache
def agentcore() -> Any:
    return boto3.client("bedrock-agentcore", config=STOP_CALL_CONFIG)


@cache
def lambda_client() -> Any:
    return boto3.client("lambda", config=SHORT_CALL_CONFIG)
