"""Trace context from the Lambda's X-Ray trace to the workflows the router starts or signals (TRACING=on).

The worker's OpenTelemetry interceptor reads a W3C traceparent from the `_tracer-data` Temporal header. The router
builds it from the X-Ray trace header Lambda sets for each invocation, so it needs no OpenTelemetry dependency.
"""

import os
import re
from collections.abc import Mapping
from typing import Any

from temporalio.api.common.v1 import Payload
from temporalio.client import (
    Interceptor,
    OutboundInterceptor,
    SignalWorkflowInput,
    StartWorkflowInput,
    WorkflowHandle,
)
from temporalio.converter import PayloadConverter

TRACE_HEADER = "_tracer-data"
XRAY_TRACE_ID_VARIABLE = "_X_AMZN_TRACE_ID"

_ROOT = re.compile(r"1-([0-9a-f]{8})-([0-9a-f]{24})")
_PARENT = re.compile(r"[0-9a-f]{16}")


def traceparent(xray_trace_id: str | None) -> str | None:
    """The W3C traceparent of an X-Ray trace header; None when the header is missing or malformed.

    `Root=1-5759e988-bd862e3fe1be46a994272793;Parent=53995c3f42cd8ad8;Sampled=1` gives
    `00-5759e988bd862e3fe1be46a994272793-53995c3f42cd8ad8-01`. Only Sampled=1 marks the trace as sampled.
    """
    if not xray_trace_id:
        return None
    fields = {}
    for field in xray_trace_id.split(";"):
        key, _, value = field.partition("=")
        fields[key] = value
    root = _ROOT.fullmatch(fields.get("Root", ""))
    parent = fields.get("Parent", "")
    if root is None or _PARENT.fullmatch(parent) is None:
        return None
    flags = "01" if fields.get("Sampled") == "1" else "00"
    return f"00-{root[1]}{root[2]}-{parent}-{flags}"


class XRayTraceInterceptor(Interceptor):
    """Puts the invocation's trace context on every workflow start and signal."""

    def intercept_client(self, next: OutboundInterceptor) -> OutboundInterceptor:
        return _TraceContextOutbound(next)


class _TraceContextOutbound(OutboundInterceptor):
    async def start_workflow(self, input: StartWorkflowInput) -> WorkflowHandle[Any, Any]:
        input.headers = _with_trace_context(input.headers)
        return await super().start_workflow(input)

    async def signal_workflow(self, input: SignalWorkflowInput) -> None:
        input.headers = _with_trace_context(input.headers)
        await super().signal_workflow(input)


def _with_trace_context(headers: Mapping[str, Payload]) -> Mapping[str, Payload]:
    # Read at each call: Lambda sets the variable anew for each invocation.
    parent = traceparent(os.environ.get(XRAY_TRACE_ID_VARIABLE))
    if parent is None:
        return headers
    # The default JSON converter, not the client's Pydantic one: the worker's interceptor decodes it with that one.
    carrier = PayloadConverter.default.to_payloads([{"traceparent": parent}])[0]
    return {**headers, TRACE_HEADER: carrier}
