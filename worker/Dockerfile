# AgentCore worker image (linux/arm64). Build context: the repository root.
#
# Three stages so the final image ships only the base and the venv: no uv, no
# source tree, no other workspace package. Bytecode is compiled at build
# time because the worker runs as uid 1000 and cannot write __pycache__, so
# without it every AgentCore cold start would recompile everything.
#
# The third-party dependencies (deps stage) and the workspace packages (app
# stage) are split across two layers in the final image on purpose: a
# code-only change in shared/src or worker/src only invalidates the small
# workspace-package layer, so pushing it over a slow uplink stays fast
# instead of re-pushing the whole venv every time.
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

# `COPY --from` flattens each wildcard match's own contents into the
# destination instead of nesting it (a Dockerfile quirk, unlike plain `cp`),
# so the two workspace packages and their dist-info directories are staged
# here first, where an ordinary `cp` can nest them correctly.
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
