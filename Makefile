.PHONY: help install install-dev type-check test test-cov build deploy clean validate local-invoke

# Default target
help: ## Show this help message
	@echo "EC2 Auto-Shutdown - Available commands:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# =============================================================================
# Development Setup
# =============================================================================

install: ## Install production dependencies only
	uv sync --no-group dev

install-dev: ## Install all dependencies (including dev)
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

test-watch: ## Run tests in watch mode (requires pytest-watch)
	uv run ptw -- --tb=short

# =============================================================================
# SAM Commands
# =============================================================================

validate: ## Validate SAM template
	sam validate --lint

build: ## Build SAM application
	sam build

build-container: ## Build SAM application using container
	sam build --use-container

deploy: build ## Build and deploy to AWS (interactive)
	sam deploy

deploy-guided: build ## Build and deploy with guided prompts
	sam deploy --guided

deploy-dev: build ## Deploy to dev environment
	sam deploy --config-env dev

deploy-prod: build ## Deploy to prod environment
	sam deploy --config-env prod

sync: ## Sync local changes to AWS (dev only)
	sam sync --watch --stack-name ec2-auto-shutdown-dev

delete: ## Delete the CloudFormation stack
	sam delete

# =============================================================================
# Local Testing
# =============================================================================

local-invoke: build ## Invoke function locally with test event
	sam local invoke ShutdownFunction --event tests/scheduled_event.json --env-vars tests/local-env.json

local-invoke-debug: build ## Invoke function locally with debug output
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
	sam logs -n ShutdownFunction --stack-name ec2-auto-shutdown --tail

update-hooks: ## Update pre-commit hooks
	uv run pre-commit autoupdate

lock: ## Update uv.lock file
	uv lock

# =============================================================================
# CI/CD Helpers
# =============================================================================

ci-check: ## Run all CI checks (pre-commit, type-check, test)
	$(MAKE) pre-commit
	$(MAKE) type-check
	$(MAKE) test-cov
	$(MAKE) validate
