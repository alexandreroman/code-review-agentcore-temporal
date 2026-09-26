"""The single Anthropic model behind every agent, declared in StrandsPlugin (worker side only).

Temporal owns retries: the Anthropic client makes one attempt (max_retries=0) with a 170 s timeout,
inside the model activity's 180 s start_to_close. The factory runs on the first model call of the
process, so the API key is read from Secrets Manager then, never passed through the environment.
"""

from agentcore_review_shared.secrets import AnthropicSecret
from strands.models import CacheConfig
from strands.models.anthropic import AnthropicModel
from temporalio.contrib.strands import StrandsPlugin

from .aws import read_secret
from .models import MODEL_NAME
from .settings import AppSettings

CLIENT_TIMEOUT_SECONDS = 170.0
MAX_TOKENS = 32_000


def strands_plugin(settings: AppSettings) -> StrandsPlugin:
    def build() -> AnthropicModel:
        api_key = AnthropicSecret.model_validate_json(read_secret(settings.anthropic_secret)).api_key
        return AnthropicModel(
            client_args={"api_key": api_key, "max_retries": 0, "timeout": CLIENT_TIMEOUT_SECONDS},
            model_id=settings.anthropic_model,
            max_tokens=MAX_TOKENS,
            params={"output_config": {"effort": settings.anthropic_effort}},
            cache_config=CacheConfig(strategy="anthropic"),
        )

    return StrandsPlugin(models={MODEL_NAME: build})
