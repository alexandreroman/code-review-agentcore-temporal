#!/usr/bin/env bash
# Builds and pushes the worker image, applies the aws stack, and makes the
# build the current Temporal Worker Deployment Version (make deploy).
#
# A Worker Deployment Version only learns its task queues when a worker of
# that version first polls, and Temporal Cloud never scales out an
# unattached version. This script therefore waits for the attachment,
# invoking the endpoint once if needed, before making the version current.
# Re-running it with unchanged, committed image inputs changes nothing: the
# image is already in ECR, the apply is a no-op, and the version is already
# current.
set -euo pipefail

source scripts/lib.sh

# Paths the worker image is built from: exactly worker/Dockerfile's COPY
# lines (every workspace member pyproject.toml, then the two source trees),
# plus the Dockerfile itself. The build ID is derived from their content,
# not from the commit SHA, so a commit that leaves these untouched (docs,
# or the tests directories the image never copies) does not redeploy: same
# image, same AgentCore endpoint, same Worker Deployment Version.
IMAGE_INPUTS=(
  pyproject.toml
  uv.lock
  shared/pyproject.toml
  router/pyproject.toml
  worker/pyproject.toml
  tools/pyproject.toml
  shared/src
  worker/src
  worker/Dockerfile
)
ATTACH_TIMEOUT=180
INVOKE_AFTER=30
POLL_EVERY=5

# image_inputs_hash prints the sha256 of the image inputs' committed object
# IDs (blob or tree SHAs), in IMAGE_INPUTS order.
image_inputs_hash() {
  local path object_ids=()
  for path in "${IMAGE_INPUTS[@]}"; do
    object_ids+=("$(git rev-parse "HEAD:${path}")")
  done
  printf '%s\n' "${object_ids[@]}" | shasum -a 256 | cut -d' ' -f1
}

build_id() {
  local hash dirty build_id
  hash=$(image_inputs_hash)
  build_id="b_${hash:0:12}"
  dirty=$(git status --porcelain -- "${IMAGE_INPUTS[@]}")
  if [[ -n "$dirty" ]]; then
    build_id="${build_id}_$(date -u +%Y%m%d%H%M%S)"
  fi
  echo "$build_id"
}

# ensure_image REPOSITORY_URL BUILD_ID: builds, self-checks and pushes the
# image, unless ECR already has this tag (tags are immutable).
ensure_image() {
  local repository_url="$1" build_id="$2"
  local repository="${repository_url#*/}"

  if aws ecr describe-images --repository-name "$repository" --image-ids "imageTag=$build_id" >/dev/null 2>&1; then
    echo "Image $build_id already in ECR"
    return
  fi

  docker info >/dev/null 2>&1 || die "Docker is not running: start it, then re-run make deploy"

  local image="${repository_url}:${build_id}"
  docker build --platform linux/arm64 -f worker/Dockerfile -t "$image" .
  docker run --rm --platform linux/arm64 "$image" python -m agentcore_review_worker.selfcheck
  aws ecr get-login-password | docker login --username AWS --password-stdin "${repository_url%%/*}"

  local attempt
  for attempt in 1 2 3; do
    docker push "$image" && return
    [[ "$attempt" -lt 3 ]] || die "docker push $image failed after 3 attempts"
    echo "docker push failed (attempt $attempt/3), retrying" >&2
  done
}

queue_attached() {
  jq -e --arg queue "$TASK_QUEUE" '[.taskQueuesInfos[]?.name] | index($queue) != null' <<<"$1" >/dev/null
}

# stack_output NAME: that output of the aws stack, read from $OUTPUTS; stops
# when it is missing or empty.
stack_output() {
  local value
  value=$(jq -r --arg name "$1" '.[$name].value // empty' <<<"$OUTPUTS")
  [[ -n "$value" ]] || die "make deploy: no $1 in the aws stack outputs (has make infra run?)"
  echo "$value"
}

# register BUILD_ID: creates the Worker Deployment Version if it does not
# exist, waits for its task queue to attach, then makes it current.
register() {
  local build_id="$1" output

  if output=$(tcli worker deployment create --name "$TEMPORAL_DEPLOYMENT_NAME" 2>&1); then
    echo "$output"
  elif [[ "$output" != *"already exists"* ]]; then
    die "$output"
  fi

  local version
  version=$(describe_version "$build_id")
  if [[ -z "$version" ]]; then
    tcli worker deployment create-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$build_id" \
      "${COMPUTE_FLAGS[@]}"
  else
    # The version may still point at a destroyed endpoint (destroy + up).
    echo "Re-applying the compute config of existing version $build_id"
    if ! output=$(tcli worker deployment update-version-compute-config \
      --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$build_id" "${COMPUTE_FLAGS[@]}" 2>&1); then
      die "Temporal refused the compute config of $build_id: $output"
    fi
  fi

  local elapsed=0 invoked=false
  version=$(describe_version "$build_id")
  while ! queue_attached "$version"; do
    if [[ "$elapsed" -ge "$ATTACH_TIMEOUT" ]]; then
      local runtime_id
      runtime_id=$(stack_output runtime_id)
      die "task queue $TASK_QUEUE never attached to $build_id: check the CloudWatch log group" \
        "/aws/bedrock-agentcore/runtimes/${runtime_id}-${build_id}"
    fi
    if [[ "$invoked" == false && "$elapsed" -ge "$INVOKE_AFTER" ]]; then
      echo "Task queue not attached after ${INVOKE_AFTER}s: invoking the endpoint"
      invoke_endpoint "$build_id"
      invoked=true
    fi
    sleep "$POLL_EVERY"
    elapsed=$((elapsed + POLL_EVERY))
    version=$(describe_version "$build_id")
  done
  echo "Task queue $TASK_QUEUE attached to $build_id"

  # An unset timestamp comes back as the Unix epoch.
  if jq -e '.currentSinceTime // "" | . != "" and (startswith("1970") | not)' <<<"$version" >/dev/null; then
    echo "$build_id is already the current version"
    return
  fi
  tcli worker deployment set-current-version --deployment-name "$TEMPORAL_DEPLOYMENT_NAME" --build-id "$build_id" \
    --yes
}

# invoke_endpoint BUILD_ID: starts one session of this build, so its worker
# polls and attaches the task queue.
invoke_endpoint() {
  local build_id="$1" runtime_arn
  runtime_arn=$(stack_output runtime_arn)
  # AWS CLI v2 expects blob parameters base64-encoded.
  aws bedrock-agentcore invoke-agent-runtime \
    --agent-runtime-arn "$runtime_arn" \
    --qualifier "$build_id" \
    --runtime-session-id "deploy-$(uuidgen | tr '[:upper:]' '[:lower:]')" \
    --payload "$(printf '{}' | base64)" \
    /dev/null >/dev/null
}

BUILD_ID=$(build_id)
echo "Deploying build $BUILD_ID"
OUTPUTS=$(aws_outputs)
ECR_REPOSITORY_URL=$(stack_output ecr_repository_url)
ensure_image "$ECR_REPOSITORY_URL" "$BUILD_ID"
scripts/infra.sh "$BUILD_ID"

# Plain assignments, so that set -e stops here if an output is missing.
OUTPUTS=$(aws_outputs)
ENDPOINT_ARN=$(stack_output current_endpoint_arn)
INVOKE_ROLE_ARN=$(stack_output temporal_invoke_role_arn)
EXTERNAL_ID=$(stack_output temporal_external_id)
COMPUTE_FLAGS=(
  --aws-agentcore-endpoint-arn "$ENDPOINT_ARN"
  --aws-agentcore-assume-role-arn "$INVOKE_ROLE_ARN"
  --aws-agentcore-assume-role-external-id "$EXTERNAL_ID"
)
register "$BUILD_ID"
