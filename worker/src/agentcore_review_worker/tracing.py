"""Opt-in tracing (TRACING=on): Temporal and Strands spans, sent to CloudWatch through the X-Ray OTLP endpoint.

Temporal's replay-safe provider gives workflow spans deterministic IDs and never emits them again on replay, which
every new AgentCore session does. The spans only show up once CloudWatch Transaction Search is enabled.
"""

import os
import time
from collections.abc import Sequence
from datetime import timedelta

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http import Compression
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from requests import PreparedRequest, Session
from requests.auth import AuthBase
from temporalio.contrib.opentelemetry import ReplaySafeTracerProvider, create_tracer_provider

SERVICE_NAME = "agentcore-review-worker"

MAX_SPAN_AGE = timedelta(hours=12)
"""Older spans are dropped at export: the endpoint rejects a whole request whose spans are over 24 hours apart."""

_provider: ReplaySafeTracerProvider | None = None


def start(environment: str, version: str | None) -> None:
    """Install the global tracer provider, once per process: OpenTelemetryPlugin needs it before the Worker starts."""
    global _provider
    if _provider is not None:
        return
    # Strands puts prompts and file contents on its spans, and X-Ray rejects spans over 200 KB: an empty allowlist
    # redacts every message attribute. Strands reads the variable when it creates its tracer, in the first agent.
    os.environ.setdefault("OTEL_SEMCONV_STABILITY_OPT_IN", "gen_ai_unredacted_attributes=")
    session = boto3.Session()
    if session.region_name is None:
        raise RuntimeError("TRACING=on needs an AWS region: set AWS_DEFAULT_REGION")
    _provider = create_provider(session, environment, version)
    trace.set_tracer_provider(_provider)


def flush() -> None:
    """Export the buffered spans: an AgentCore session stops its microVM right after the worker drains."""
    if _provider is not None:
        _provider.force_flush()


def create_provider(session: boto3.Session, environment: str, version: str | None) -> ReplaySafeTracerProvider:
    attributes = {"service.name": SERVICE_NAME, "deployment.environment": environment}
    if version is not None:
        attributes["service.version"] = version
    exporter = OTLPSpanExporter(
        endpoint=f"https://xray.{session.region_name}.amazonaws.com/v1/traces",
        compression=Compression.Gzip,
        session=_signed_session(session),
    )
    provider = create_tracer_provider(resource=Resource.create(attributes))
    provider.add_span_processor(BatchSpanProcessor(_RecentSpansExporter(exporter)))
    return provider


def _signed_session(session: boto3.Session) -> Session:
    signed = Session()
    signed.auth = _SigV4(session)
    return signed


class _SigV4(AuthBase):
    """Signs each export request for X-Ray with the process's AWS credentials."""

    def __init__(self, session: boto3.Session) -> None:
        self._session = session

    def __call__(self, request: PreparedRequest) -> PreparedRequest:
        # Read per request: temporary credentials (the AgentCore role, an SSO login) are refreshed in between.
        credentials = self._session.get_credentials().get_frozen_credentials()
        aws_request = AWSRequest(
            method=request.method,
            url=request.url,
            data=request.body,
            headers={"Content-Type": request.headers["Content-Type"]},
        )
        SigV4Auth(credentials, "xray", self._session.region_name).add_auth(aws_request)
        request.headers.update(aws_request.headers.items())
        return request


class _RecentSpansExporter(SpanExporter):
    """Drops the spans started over MAX_SPAN_AGE ago, then exports the others (Decorator pattern).

    Only the pull request workflow's run span lasts that long, on a pull request open for days: without this, the
    endpoint would reject it together with every other span of its batch.
    """

    def __init__(self, exporter: SpanExporter) -> None:
        self._exporter = exporter

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        oldest_start = time.time_ns() - int(MAX_SPAN_AGE.total_seconds() * 1_000_000_000)
        recent = [span for span in spans if span.start_time is not None and span.start_time >= oldest_start]
        if not recent:
            return SpanExportResult.SUCCESS
        return self._exporter.export(recent)

    def shutdown(self) -> None:
        self._exporter.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._exporter.force_flush(timeout_millis)
