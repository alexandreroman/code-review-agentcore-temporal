# AgentCore worker image (linux/arm64), built from the repository root. The final image adds only the venv to the base,
# with bytecode compiled at build time (uid 1000 cannot write __pycache__) and the workspace packages in a layer of
# their own: a code change pushes that small layer, not the whole venv.
FROM python:3.14-slim AS deps

COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Third-party dependencies only (cached until uv.lock changes). Every member manifest is needed to read the workspace.
COPY pyproject.toml uv.lock ./
COPY shared/pyproject.toml shared/
COPY router/pyproject.toml router/
COPY worker/pyproject.toml worker/
COPY tools/pyproject.toml tools/
RUN uv sync --frozen --no-dev --package agentcore-review-worker --no-install-workspace

FROM deps AS app

# Then the code: only the packages the worker runs, installed into the same
# venv as the third-party dependencies above. No .env, no certificates.
COPY shared/src shared/src
COPY worker/src worker/src
RUN uv sync --frozen --no-dev --package agentcore-review-worker --no-editable

# `COPY --from` would flatten each wildcard match: the packages and dist-info are staged here, where cp nests them.
RUN mkdir -p /out && cp -a \
      /app/.venv/lib/python3.14/site-packages/agentcore_review_worker* \
      /app/.venv/lib/python3.14/site-packages/agentcore_review_shared* \
      /out/

FROM python:3.14-slim

# Third-party venv (cached)
COPY --from=deps /app/.venv /app/.venv
# Workspace packages (changes with the code)
COPY --from=app /out/ /app/.venv/lib/python3.14/site-packages/
ENV PATH=/app/.venv/bin:$PATH
WORKDIR /app

USER 1000
EXPOSE 8080
CMD ["python", "-m", "agentcore_review_worker.agentcore"]
