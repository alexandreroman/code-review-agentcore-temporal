# Developer task runner. Run `make` (or `make help`) to list the targets.
# Compatible with GNU Make 3.81 (the macOS default): each recipe line runs
# in its own shell, so multi-line logic joins lines with `\`.

.DEFAULT_GOAL := help
SHELL := /bin/bash

# Canonical environment. A missing .env file is not an error.
-include .env

# Defaults for every setting .env may leave out (documented in .env.example).
AWS_REGION ?= ca-central-1
TEMPORAL_NAMESPACE ?=
TEMPORAL_TLS_CERT_PATH ?= certs/client.pem
TEMPORAL_TLS_KEY_PATH ?= certs/client.key
TEMPORAL_WORKER_CERT_PATH ?= $(TEMPORAL_TLS_CERT_PATH)
TEMPORAL_WORKER_KEY_PATH ?= $(TEMPORAL_TLS_KEY_PATH)
TEMPORAL_ROUTER_CERT_PATH ?= $(TEMPORAL_TLS_CERT_PATH)
TEMPORAL_ROUTER_KEY_PATH ?= $(TEMPORAL_TLS_KEY_PATH)
TEMPORAL_DEPLOYMENT_NAME ?= agentcore-review-demo-worker
TASK_QUEUE ?= review
DEV_TASK_QUEUE ?= review-dev
DEV_BRANCH_PREFIX ?= dev/
ANTHROPIC_API_KEY ?=
ANTHROPIC_MODEL ?= claude-opus-5
ANTHROPIC_EFFORT ?= high
MAX_PARALLEL_AGENTS ?= 3
DEMO_REPO ?= agentcore-review-demo-app
GITHUB_APP_NAME ?= temporal-agentcore-review-demo
AGENTCORE_IDLE_TIMEOUT ?= 120
GITHUB_APP_CALLBACK_PORT ?= 8765

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
	TEMPORAL_WORKER_CERT_PATH TEMPORAL_WORKER_KEY_PATH TEMPORAL_ROUTER_CERT_PATH TEMPORAL_ROUTER_KEY_PATH \
	TEMPORAL_DEPLOYMENT_NAME TASK_QUEUE DEV_TASK_QUEUE DEV_BRANCH_PREFIX ANTHROPIC_API_KEY ANTHROPIC_MODEL \
	ANTHROPIC_EFFORT MAX_PARALLEL_AGENTS DEMO_REPO
export AWS_DEFAULT_REGION = $(AWS_REGION)

# OpenTofu input variables (no secret among them).
export TF_VAR_region = $(AWS_REGION)
export TF_VAR_temporal_address = $(TEMPORAL_ADDRESS)
export TF_VAR_temporal_namespace = $(TEMPORAL_NAMESPACE)
export TF_VAR_task_queue = $(TASK_QUEUE)
export TF_VAR_dev_task_queue = $(DEV_TASK_QUEUE)
export TF_VAR_dev_branch_prefix = $(DEV_BRANCH_PREFIX)
export TF_VAR_deployment_name = $(TEMPORAL_DEPLOYMENT_NAME)
export TF_VAR_anthropic_model = $(ANTHROPIC_MODEL)
export TF_VAR_anthropic_effort = $(ANTHROPIC_EFFORT)
export TF_VAR_max_parallel_agents = $(MAX_PARALLEL_AGENTS)
export TF_VAR_idle_timeout = $(AGENTCORE_IDLE_TIMEOUT)
export TF_VAR_demo_repo = $(DEMO_REPO)

PROJECT := temporal-agentcore-review-demo
NAMESPACE_PLACEHOLDER := your-namespace.a1b2c
TOOLS := uv run --quiet python -m agentcore_review_tools
TOFU_BOOTSTRAP := tofu -chdir=infra/bootstrap
TOFU_AWS := tofu -chdir=infra/aws
TOFU_GITHUB := tofu -chdir=infra/github
# Expanded by the shell of the recipe that uses it, so STS is only called then.
STATE_BUCKET = $(PROJECT)-tfstate-$$(aws sts get-caller-identity --query Account --output text)

# $(call require,VAR,hint): stop the target when VAR is empty.
require = $(if $(strip $($(1))),,$(error $(1) is not set: $(2)))
# Stop the target while TEMPORAL_NAMESPACE is empty or still the placeholder.
require_namespace = $(if $(filter-out $(NAMESPACE_PLACEHOLDER),$(strip $(TEMPORAL_NAMESPACE))),,$(error \
	TEMPORAL_NAMESPACE is not set: put your Temporal Cloud namespace in .env))
# $(call set_env,KEY,VALUE): replace or append KEY=VALUE in .env (idempotent).
set_env = if grep -q '^$(1)=' .env; then sed -i.bak "s|^$(1)=.*|$(1)=$(2)|" .env && rm -f .env.bak; \
	else echo "$(1)=$(2)" >> .env; fi

##@ Develop

.PHONY: install
install: ## Install every workspace package and the dev tools
	uv sync --all-packages

.PHONY: dev
dev: infra-init ## Run the local worker (dev task queue on Temporal Cloud) with hot reload
	$(call require_namespace)
	@GITHUB_OWNER=$(GITHUB_OWNER) scripts/dev.sh

# Manual driver, as the router does from webhooks: make review-pr PR=3 [ACTION=fix] [QUEUE=review]
PR ?=
ACTION ?= update
QUEUE ?= $(DEV_TASK_QUEUE)

.PHONY: review-pr
review-pr: ## Drive a pull request's workflow by hand: PR=<n> [ACTION=update|fix|close] [QUEUE=<queue>]
	$(call require_namespace)
	$(call require,PR,pass the pull request number: make review-pr PR=<n>)
	$(call require,GITHUB_OWNER,log in with gh or set GITHUB_OWNER in .env)
	scripts/review-pr.sh "$(GITHUB_OWNER)" "$(DEMO_REPO)" "$(PR)" "$(ACTION)" "$(QUEUE)"

# Casper gives each worktree a band of ports starting at CASPER_PORT; the
# local port is derived from it once, here, and .env stays the only source.
.PHONY: worktree-init
worktree-init: ## Prepare a new worktree: .env, dependencies, local port
	@[ -f .env ] || cp .env.example .env
	uv sync --all-packages
	@if [ -n "$${CASPER_PORT:-}" ]; then \
		$(call set_env,GITHUB_APP_CALLBACK_PORT,$$((CASPER_PORT + 0))); \
	fi

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

STACKS := bootstrap aws github

.PHONY: infra-check
infra-check: ## Check OpenTofu formatting and validate every stack (no AWS access needed)
	tofu fmt -check -recursive infra
	@for stack in $(STACKS); do \
		TF_DATA_DIR=.terraform-validate tofu -chdir=infra/$$stack init -backend=false -input=false >/dev/null && \
		TF_DATA_DIR=.terraform-validate tofu -chdir=infra/$$stack validate -no-color || exit 1; \
	done

.PHONY: check
check: test lint infra-check ## Run tests and static checks

##@ Deploy

.PHONY: bootstrap
bootstrap: ## Create the OpenTofu state bucket and KMS key (once per AWS account)
	@bucket=$(STATE_BUCKET) && \
	if aws s3api head-bucket --bucket "$$bucket" >/dev/null 2>&1; then \
		echo "State bucket $$bucket already exists"; \
	else \
		$(TOFU_BOOTSTRAP) init -input=false && $(TOFU_BOOTSTRAP) apply -input=false -auto-approve; \
	fi

.PHONY: infra-init
infra-init: ## Initialise the OpenTofu backends (S3 state, per worktree)
	$(TOFU_AWS) init -input=false -backend-config="bucket=$(STATE_BUCKET)" \
		-backend-config="region=$(AWS_REGION)" >/dev/null
	$(TOFU_GITHUB) init -input=false -backend-config="bucket=$(STATE_BUCKET)" \
		-backend-config="region=$(AWS_REGION)" >/dev/null

.PHONY: infra
infra: router-build infra-init ## Apply the aws stack (keeps the deployed build and its endpoints)
	$(call require_namespace)
	scripts/infra.sh

.PHONY: secrets
secrets: ## Push the Anthropic key and the mTLS certificates from .env to Secrets Manager
	scripts/secrets.sh

.PHONY: github-app
github-app: infra-init ## Register the GitHub App through the manifest flow (interactive, once)
	$(call require,GITHUB_OWNER,log in with gh or set GITHUB_OWNER in .env)
	$(TOOLS).github_app register --owner $(GITHUB_OWNER) --name $(GITHUB_APP_NAME) \
		--port $(GITHUB_APP_CALLBACK_PORT) --webhook-url "$$($(TOFU_AWS) output -raw router_url)" \
		$(if $(FORCE),--force)

.PHONY: require-github-app
require-github-app:
	@aws secretsmanager get-secret-value --secret-id $(PROJECT)/github-app --query ARN --output text >/dev/null 2>&1 \
		|| { echo "The GitHub App is not registered yet: run make github-app, then make up again."; exit 1; }

.PHONY: github
github: infra-init require-github-app ## Apply the github stack (demo repository, ruleset, Actions secrets)
	$(call require,GITHUB_OWNER,log in with gh or set GITHUB_OWNER in .env)
	GITHUB_TOKEN=$$(gh auth token) TF_VAR_github_owner=$(GITHUB_OWNER) \
		TF_VAR_app_installed=$$($(TOOLS).github_app installation-id --owner $(GITHUB_OWNER) --repo $(DEMO_REPO) \
			>/dev/null 2>&1 && echo true || echo false) \
		$(TOFU_GITHUB) apply -input=false -auto-approve

.PHONY: deploy
deploy: router-build infra-init ## Build and push the worker image, then make it the current Worker Deployment Version
	$(call require_namespace)
	scripts/deploy.sh

.PHONY: up
up: ## Deploy everything: state, AWS, secrets, worker, GitHub (idempotent, stops at a missing prerequisite)
	$(call require_namespace)
	$(MAKE) --no-print-directory bootstrap
	$(MAKE) --no-print-directory infra
	$(MAKE) --no-print-directory secrets
	$(MAKE) --no-print-directory deploy
	$(MAKE) --no-print-directory github
	$(TOOLS).github_app check-install --owner $(GITHUB_OWNER) --repo $(DEMO_REPO)
	$(MAKE) --no-print-directory info-publish

.PHONY: kill-sessions
kill-sessions: infra-init ## Stop every AgentCore session polling the production task queue
	$(call require_namespace)
	scripts/kill-sessions.sh

.PHONY: prune
prune: router-build infra-init ## Remove the endpoints and versions of builds no workflow is pinned to any more
	$(call require_namespace)
	scripts/prune.sh

.PHONY: destroy
destroy: router-build infra-init ## Destroy the AWS resources (asks for confirmation; GitHub and the state bucket stay)
	$(call require_namespace)
	scripts/destroy.sh

.PHONY: ping
ping: ## Run the Ping workflow on the production task queue (scale-from-zero check)
	$(call require_namespace)
	temporal workflow execute --type Ping --task-queue $(TASK_QUEUE) --workflow-id ping-$$(date +%s) \
		--input '"hello"' --tls-cert-path $(TEMPORAL_TLS_CERT_PATH) --tls-key-path $(TEMPORAL_TLS_KEY_PATH)

.PHONY: router-build
router-build: ## Build the router Lambda: code into build/router, dependency layer into build/router-deps
	scripts/router-build.sh

##@ Workspace

.PHONY: info-publish
info-publish: ## Publish endpoints and links to the workspace info panel
	-@GITHUB_OWNER=$(GITHUB_OWNER) scripts/info-panel.sh

##@ Helpers

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(firstword $(MAKEFILE_LIST))

# Debug helper, hidden from help: make -s print-TEMPORAL_ADDRESS
print-%:
	@echo '$($*)'
