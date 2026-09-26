#!/usr/bin/env bash
# Builds the router Lambda for python3.14 on arm64 (make router-build), in two parts:
#   build/router/              the router and shared packages only: the function zip (a few KB)
#   build/router-deps/python/  third-party dependencies: a Lambda layer
# The layer changes only with uv.lock, so a code change uploads kilobytes instead of ~25 MB.
set -euo pipefail

PLATFORM=aarch64-manylinux2014
CODE=build/router
LAYER=build/router-deps
DEPS="$LAYER/python"
# Provided by the Lambda runtime (boto3 and its dependencies), or type stubs never imported.
EXCLUDED=(boto3 botocore s3transfer jmespath python-dateutil six urllib3 types-protobuf)

rm -rf "$CODE" "$LAYER"
mkdir -p "$CODE" "$DEPS"

exclude_args=()
for package in "${EXCLUDED[@]}"; do
  exclude_args+=(--no-emit-package "$package")
done
uv export --quiet --frozen --package agentcore-review-router --no-dev --no-hashes --no-emit-workspace \
  "${exclude_args[@]}" -o build/router-requirements.txt

lambda_install() {
  uv pip install --quiet --python-platform "$PLATFORM" --python-version 3.14 \
    --no-installer-metadata --no-compile-bytecode "$@"
}
# --no-deps: the export already is the full closure; resolving again would bring the excluded packages back.
lambda_install --target "$DEPS" --only-binary :all: --no-deps -r build/router-requirements.txt
lambda_install --target "$CODE" --no-deps ./shared ./router

# Rust sources shipped inside the temporalio wheel, never loaded at run time (~10 MB unzipped).
rm -rf "$DEPS/temporalio/bridge/sdk-core" "$DEPS/temporalio/bridge/src" "$DEPS"/temporalio/bridge/Cargo.*

# The Lambda cannot write __pycache__, so ship the bytecode. unchecked-hash .pyc files ignore file timestamps:
# they stay valid in the zip and keep it reproducible (an unchanged build uploads nothing).
uv run --quiet python -m compileall -q -j 0 --invalidation-mode unchecked-hash "$DEPS" "$CODE" >/dev/null

echo "router code: $(du -sh "$CODE" | cut -f1), dependency layer: $(du -sh "$LAYER" | cut -f1) (unzipped)"
