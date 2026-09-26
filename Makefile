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
TEMPORAL_DEPLOYMENT_NAME ?= agentic-review
TASK_QUEUE ?= review
DEV_TASK_QUEUE ?= review-dev
DEV_BRANCH_PREFIX ?= dev/
ANTHROPIC_API_KEY ?=
ANTHROPIC_MODEL ?= claude-opus-5
ANTHROPIC_EFFORT ?= high
MAX_PARALLEL_AGENTS ?= 3
DEMO_REPO ?= temporal-agentic-review-demo
GITHUB_APP_NAME ?= temporal-agentic-review
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
# Connection settings of the temporal CLI (mTLS).
export TEMPORAL_TLS_CLIENT_CERT_PATH = $(abspath $(TEMPORAL_TLS_CERT_PATH))
export TEMPORAL_TLS_CLIENT_KEY_PATH = $(abspath $(TEMPORAL_TLS_KEY_PATH))

PROJECT := temporal-agentic-review
NAMESPACE_PLACEHOLDER := your-namespace.a1b2c
TOOLS := uv run --quiet python -m agentic_review_tools
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
dev: ## Run the local worker (dev task queue on Temporal Cloud) with hot reload
	$(call require_namespace)
	@# The trap reaps the whole process group (kill 0) on exit or signal, so no
	@# orphaned processes survive Ctrl-C or a child crash.
	@trap 'kill 0' EXIT INT TERM; \
		uv run watchfiles 'python -m agentic_review_worker' worker/src shared/src & \
		wait

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

.PHONY: check
check: test lint infra-check ## Run tests and static checks

##@ Deploy

.PHONY: secrets
secrets: ## Push the Anthropic key and the mTLS certificates from .env to Secrets Manager
	$(TOOLS).secrets_sync

LAMBDA_PLATFORM := aarch64-manylinux2014
ROUTER_BUILD := build/router

.PHONY: router-build
router-build: ## Build the router Lambda package (python3.14, arm64) into build/router
	rm -rf $(ROUTER_BUILD) && mkdir -p $(ROUTER_BUILD)
	uv export --quiet --frozen --package agentic-review-router --no-dev --no-hashes --no-emit-workspace \
		-o build/router-requirements.txt
	uv pip install --quiet --target $(ROUTER_BUILD) --python-platform $(LAMBDA_PLATFORM) --python-version 3.14 \
		--only-binary :all: --no-installer-metadata --no-compile-bytecode -r build/router-requirements.txt
	uv pip install --quiet --target $(ROUTER_BUILD) --python-platform $(LAMBDA_PLATFORM) --python-version 3.14 \
		--no-deps --no-installer-metadata --no-compile-bytecode ./shared ./router

##@ Helpers

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(firstword $(MAKEFILE_LIST))

# Debug helper, hidden from help: make -s print-TEMPORAL_ADDRESS
print-%:
	@echo '$($*)'
