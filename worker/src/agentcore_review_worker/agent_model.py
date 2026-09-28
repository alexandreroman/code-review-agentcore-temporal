"""The single Claude model on Amazon Bedrock behind every agent, declared in StrandsPlugin (worker side only).

Requests go through the Converse API, signed with the caller's AWS credentials: the runtime role on AgentCore, the
developer's in the dev worker. The region comes from the standard boto3 resolution, as for the worker's other AWS
clients: AWS_DEFAULT_REGION (exported by the Makefile in dev, provided by the runtime on AgentCore) or the profile.

Temporal owns retries: the Bedrock client makes one attempt with a 170 s read timeout, inside the model activity's
180 s start_to_close, and a Bedrock error reaches Temporal typed by its error code (see MODEL_RETRY).
"""

from collections.abc import AsyncGenerator
from typing import Any

from botocore.config import Config
from botocore.exceptions import ClientError
from strands.models import CacheConfig
from strands.models.bedrock import BedrockModel
from strands.types.streaming import StreamEvent
from temporalio.contrib.strands import StrandsPlugin
from temporalio.exceptions import ApplicationError

from .models import MODEL_NAME
from .settings import AppSettings

MAX_TOKENS = 32_000
CLIENT_CONFIG = Config(connect_timeout=10, read_timeout=170, retries={"total_max_attempts": 1})


class TypedErrorBedrockModel(BedrockModel):
    """A BedrockModel whose Bedrock errors carry their error code as the Temporal error type.

    Strands raises a raw botocore ClientError for every Bedrock error but throttling and context overflow, and the
    Temporal failure converter types them all "ClientError": the retry policy could not tell a bad request from a
    transient failure. The region and model go into the message: Temporal does not serialize exception notes.
    """

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[StreamEvent]:
        try:
            async for event in super().stream(*args, **kwargs):
                yield event
        except ClientError as error:
            message = f"{error} (region {self.client.meta.region_name}, model {self.config['model_id']})"
            raise ApplicationError(message, type=_error_type(error)) from error


def _error_type(error: ClientError) -> str:
    """The Bedrock error code, capitalized: mid-stream errors spell it in lower camel case (validationException)."""
    code = error.response["Error"]["Code"]
    return code[:1].upper() + code[1:]


def strands_plugin(settings: AppSettings) -> StrandsPlugin:
    def build() -> BedrockModel:
        return TypedErrorBedrockModel(
            boto_client_config=CLIENT_CONFIG,
            model_id=settings.bedrock_model_id,
            max_tokens=MAX_TOKENS,
            additional_request_fields={"output_config": {"effort": settings.model_effort}},
            cache_config=CacheConfig(strategy="anthropic"),
        )

    return StrandsPlugin(models={MODEL_NAME: build})
