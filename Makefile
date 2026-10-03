.PHONY: help install install-dev type-check pre-commit test test-cov \
	validate build build-container check-config check-local-env deploy \
	deploy-guided delete local-invoke local-invoke-debug clean logs \
	update-hooks lock ci-check

# Default target
help: ## Show this help message
	@echo "Server Saver - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Development Setup
# =============================================================================

install: ## Install production dependencies only
	uv sync --no-group dev

install-dev: ## Install all dependencies (including dev) and pre-commit hooks
	uv sync
	uv run pre-commit install

# =============================================================================
# Code Quality
# =============================================================================

type-check: ## Run type checker (mypy)
	uv run mypy src/

pre-commit: ## Run pre-commit on all files
	uv run pre-commit run --all-files

# =============================================================================
# Testing
# =============================================================================

test: ## Run tests
	uv run pytest

test-cov: ## Run tests with coverage report
	uv run pytest --cov=src --cov-report=term-missing --cov-report=html

# =============================================================================
# Configuration Checks
# =============================================================================

check-config: ## Ensure samconfig.toml exists
	@test -f samconfig.toml || (echo "samconfig.toml not found. Run: cp samconfig.example.toml samconfig.toml" && exit 1)

check-local-env: ## Ensure tests/local-env.json exists
	@test -f tests/local-env.json || (echo "tests/local-env.json not found. Run: cp tests/local-env.json.example tests/local-env.json" && exit 1)

# =============================================================================
# SAM Commands
# =============================================================================

validate: ## Validate SAM template
	sam validate --lint

build: ## Build SAM application
	sam build

build-container: ## Build SAM application using container
	sam build --use-container

deploy: check-config build ## Build and deploy to AWS (uses samconfig.toml)
	sam deploy

deploy-guided: build ## Build and deploy with guided prompts (writes samconfig.toml)
	sam deploy --guided

delete: check-config ## Delete the CloudFormation stack
	sam delete

# =============================================================================
# Local Testing
# =============================================================================

local-invoke: check-local-env build ## Invoke function locally with test event
	sam local invoke ShutdownFunction --event tests/scheduled_event.json --env-vars tests/local-env.json

local-invoke-debug: check-local-env build ## Invoke function locally with debug output
	sam local invoke ShutdownFunction --event tests/scheduled_event.json --env-vars tests/local-env.json --debug

# =============================================================================
# Utilities
# =============================================================================

clean: ## Remove build artifacts
	rm -rf .aws-sam/
	rm -rf .pytest_cache/
	rm -rf .mypy_cache/
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf *.egg-info/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete

logs: ## Tail Lambda logs (requires deployed function)
	sam logs -n ShutdownFunction --stack-name server-saver --tail

update-hooks: ## Update pre-commit hooks
	uv run pre-commit autoupdate

lock: ## Update uv.lock file
	uv lock

# =============================================================================
# CI/CD Helpers
# =============================================================================

ci-check: ## Run all CI checks (pre-commit, type-check, test, validate)
	$(MAKE) pre-commit
	$(MAKE) type-check
	$(MAKE) test-cov
	$(MAKE) validate
