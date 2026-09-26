# AgentCore worker image (linux/arm64). Build context: the repository root.
FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH
WORKDIR /app

# Third-party dependencies first (cached until uv.lock changes). Every member manifest is needed to read the workspace.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY router/pyproject.toml router/
COPY worker/pyproject.toml worker/
COPY tools/pyproject.toml tools/
RUN uv sync --frozen --no-dev --package agentic-review-worker --no-install-workspace

# Then the code: only the packages the worker runs. No .env, no certificates.
COPY shared/src shared/src
COPY worker/src worker/src
RUN uv sync --frozen --no-dev --package agentic-review-worker --no-editable

USER 1000
EXPOSE 8080
CMD ["python", "-m", "agentic_review_worker.agentcore"]
