# Developer task runner. Run `make` (or `make help`) to list the targets.
# Compatible with GNU Make 3.81 (the macOS default): no `.ONESHELL` in 3.81,
# so each recipe line runs in its own shell and logic lives in scripts/.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Canonical environment. A missing .env file is not an error.
-include .env

# Defaults for every setting .env may leave out (documented in .env.example).
AWS_REGION ?= ca-central-1
TEMPORAL_TLS_CERT_PATH ?= certs/client.pem
TEMPORAL_TLS_KEY_PATH ?= certs/client.key
TEMPORAL_DEPLOYMENT_NAME ?= agentcore-review-demo-worker
TASK_QUEUE ?= review
DEV_TASK_QUEUE ?= review-dev
DEV_BRANCH_PREFIX ?= dev/
PR_IDLE_WARNING_SECONDS ?= 600
PR_IDLE_CLOSE_SECONDS ?= 900
BEDROCK_MODEL_ID ?= global.anthropic.claude-opus-5
MODEL_EFFORT ?= high
MAX_PARALLEL_AGENTS ?= 3
DEMO_REPO ?= agentcore-review-demo-app
GITHUB_APP_NAME ?= Code Review AgentCore x Temporal
GITHUB_APP_CALLBACK_PORT ?= 8765
SUBDOMAIN ?= codereview
TRACING ?= off

# Derived defaults, also applied when .env sets these to an empty value.
ifeq ($(strip $(TEMPORAL_ADDRESS)),)
TEMPORAL_ADDRESS = $(TEMPORAL_NAMESPACE).tmprl.cloud:7233
endif
ifeq ($(strip $(GITHUB_OWNER)),)
# Recursive on purpose: gh only runs when a recipe uses the owner.
GITHUB_OWNER = $(shell gh api user --jq .login 2>/dev/null)
endif

# Settings read by the worker, the tools and the CLIs. The list is explicit:
# a bare `export` would expand $(GITHUB_OWNER), hence run gh, for every recipe.
export AWS_REGION TEMPORAL_NAMESPACE TEMPORAL_ADDRESS TEMPORAL_TLS_CERT_PATH TEMPORAL_TLS_KEY_PATH \
	TEMPORAL_DEPLOYMENT_NAME TASK_QUEUE DEV_TASK_QUEUE PR_IDLE_WARNING_SECONDS PR_IDLE_CLOSE_SECONDS \
	BEDROCK_MODEL_ID MODEL_EFFORT MAX_PARALLEL_AGENTS DEMO_REPO GITHUB_APP_NAME \
	GITHUB_APP_CALLBACK_PORT DOMAIN_NAME CLOUDFLARE_ZONE_ID CLOUDFLARE_API_TOKEN TRACING
export AWS_DEFAULT_REGION = $(AWS_REGION)

# OpenTofu input variables (no secret among them: the Cloudflare provider reads CLOUDFLARE_API_TOKEN itself).
export TF_VAR_region = $(AWS_REGION)
export TF_VAR_temporal_address = $(TEMPORAL_ADDRESS)
export TF_VAR_temporal_namespace = $(TEMPORAL_NAMESPACE)
export TF_VAR_task_queue = $(TASK_QUEUE)
export TF_VAR_dev_task_queue = $(DEV_TASK_QUEUE)
export TF_VAR_dev_branch_prefix = $(DEV_BRANCH_PREFIX)
export TF_VAR_pr_idle_warning_seconds = $(PR_IDLE_WARNING_SECONDS)
export TF_VAR_pr_idle_close_seconds = $(PR_IDLE_CLOSE_SECONDS)
export TF_VAR_deployment_name = $(TEMPORAL_DEPLOYMENT_NAME)
export TF_VAR_bedrock_model_id = $(BEDROCK_MODEL_ID)
export TF_VAR_model_effort = $(MODEL_EFFORT)
export TF_VAR_max_parallel_agents = $(MAX_PARALLEL_AGENTS)
export TF_VAR_demo_repo = $(DEMO_REPO)
export TF_VAR_domain_name = $(DOMAIN_NAME)
export TF_VAR_subdomain = $(SUBDOMAIN)
export TF_VAR_cloudflare_zone_id = $(CLOUDFLARE_ZONE_ID)
export TF_VAR_tracing = $(TRACING)

PROJECT := code-review-agentcore-temporal
NAMESPACE_PLACEHOLDER := your-namespace.a1b2c
TOFU_AWS := tofu -chdir=infra/aws
TOFU_GITHUB := tofu -chdir=infra/github
# Expanded by the shell of the recipe that uses it, so STS is only called then.
STATE_BUCKET = $(PROJECT)-tfstate-$$(aws sts get-caller-identity --query Account --output text)

# $(call require,VAR,hint): stop the target when VAR is empty.
require = $(if $(strip $($(1))),,$(error $(1) is not set: $(2)))
# Stop the target while TEMPORAL_NAMESPACE is empty or still the placeholder.
require_namespace = $(if $(filter-out $(NAMESPACE_PLACEHOLDER),$(strip $(TEMPORAL_NAMESPACE))),,$(error \
	TEMPORAL_NAMESPACE is not set: put your Temporal Cloud namespace in .env))

# Listed first among the prerequisites of the targets that need the namespace, so that a missing one stops them
# before their slower prerequisites run (a recipe is only expanded after its prerequisites are built).
.PHONY: namespace
namespace:
	$(call require_namespace)

##@ Develop

.PHONY: install
install: ## Install every workspace package and the dev tools
	uv sync --all-packages

.PHONY: dev
dev: namespace infra-init ## Run the local worker (dev task queue on Temporal Cloud) with hot reload
	@GITHUB_OWNER=$(GITHUB_OWNER) scripts/dev.sh

##@ Quality

.PHONY: test
test: ## Run the unit tests
	uv run pytest -q

.PHONY: lint
lint: ## Check formatting and lint rules
	uv run ruff format --check .
	uv run ruff check .

.PHONY: format
format: ## Format the code
	uv run ruff format .

.PHONY: infra-check
infra-check: ## Check OpenTofu formatting and validate every stack (no AWS access needed)
	scripts/infra-check.sh

.PHONY: check
check: test lint infra-check ## Run tests and static checks

##@ Deploy

# Create the OpenTofu state bucket and KMS key (once per AWS account).
.PHONY: bootstrap
bootstrap:
	@scripts/bootstrap.sh "$(STATE_BUCKET)"

# Initialise the OpenTofu backends (S3 state, per worktree). -reconfigure: the
# bucket comes from the command line on every run, so a saved backend
# configuration never needs migrating.
.PHONY: infra-init
infra-init:
	$(TOFU_AWS) init -reconfigure -input=false -backend-config="bucket=$(STATE_BUCKET)" \
		-backend-config="region=$(AWS_REGION)" >/dev/null
	$(TOFU_GITHUB) init -reconfigure -input=false -backend-config="bucket=$(STATE_BUCKET)" \
		-backend-config="region=$(AWS_REGION)" >/dev/null

# Apply the aws stack (keeps the deployed build and its endpoints).
# infra, deploy, prune and destroy depend on router-build: every plan of the aws
# stack, destroy included, reads build/router through archive_file data sources.
.PHONY: infra
infra: namespace router-build infra-init
	scripts/infra.sh

# Push the mTLS client certificate from .env to Secrets Manager (read by the worker and the router).
.PHONY: secrets
secrets:
	scripts/secrets.sh

# Register the GitHub App if needed (interactive; FORCE=1 registers a new app over the stored one), sync it (slug,
# webhook), apply the github stack (demo repository, rulesets, Actions secrets) and push the demo application from
# demo/ into an empty demo repository.
.PHONY: github
github: infra-init
	$(call require,GITHUB_OWNER,log in with gh or set GITHUB_OWNER in .env)
	@GITHUB_OWNER=$(GITHUB_OWNER) scripts/github.sh

# Build and push the worker image, then make it the current Worker Deployment Version.
.PHONY: deploy
deploy: namespace router-build infra-init
	scripts/deploy.sh

.PHONY: up
up: namespace ## Deploy everything: state, AWS, secrets, worker, GitHub App and demo repository (idempotent)
	$(MAKE) --no-print-directory bootstrap infra secrets deploy github info-publish

.PHONY: kill-sessions
kill-sessions: namespace infra-init ## Stop every AgentCore session polling the production task queue
	scripts/kill-sessions.sh

.PHONY: prune
prune: namespace router-build infra-init ## Remove the endpoints and versions of builds no workflow is pinned to
	scripts/prune.sh

.PHONY: delete-workflows
delete-workflows: namespace ## Delete every closed workflow execution of the namespace (running ones are kept)
	scripts/delete-workflows.sh

.PHONY: destroy
destroy: namespace router-build infra-init ## Destroy the AWS resources (asks first; GitHub and the state bucket stay)
	scripts/destroy.sh

.PHONY: ping
ping: namespace ## Run the Ping workflow on the production task queue (scale-from-zero check)
	temporal workflow execute --type Ping --task-queue $(TASK_QUEUE) --workflow-id ping-$$(date +%s) \
		--input '"hello"' --tls-cert-path $(TEMPORAL_TLS_CERT_PATH) --tls-key-path $(TEMPORAL_TLS_KEY_PATH)

# Build the router Lambda: code into build/router, dependency layer into build/router-deps.
.PHONY: router-build
router-build:
	scripts/router-build.sh

# Publish endpoints and links to the workspace info panel (best effort).
.PHONY: info-publish
info-publish:
	-@GITHUB_OWNER=$(GITHUB_OWNER) scripts/info-panel.sh

##@ Helpers

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(firstword $(MAKEFILE_LIST))

# Prints a resolved setting (used by the e2e-validation skill): make -s print-VAR
print-%:
	@echo '$($*)'
