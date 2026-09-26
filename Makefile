# Developer task runner. Run `make` (or `make help`) to
# list the available targets.

.DEFAULT_GOAL := help

# Canonical environment, loaded for every target.
# A missing .env file is not an error.
ifneq (,$(wildcard .env))
include .env
export
endif

##@ Develop

.PHONY: install
install: ## Install every workspace package and the dev tools
	uv sync --all-packages

.PHONY: dev
dev: ## Run the local worker (review-dev queue on Temporal Cloud) with hot reload
	# Trap reaps the whole process group (kill 0) on exit or signal, so no
	# orphaned processes survive Ctrl-C or a child crash.
	@trap 'kill 0' EXIT INT TERM; \
		uv run watchfiles 'python -m agentic_review_worker' worker/src shared/src & \
		wait

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
check: test lint ## Run tests and static checks

##@ Helpers

.PHONY: help
help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "Usage: make \033[36m<target>\033[0m\n"} \
		/^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2 } \
		/^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) }' $(firstword $(MAKEFILE_LIST))
