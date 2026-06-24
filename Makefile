.PHONY: help test test-unit test-integration test-all test-smoke test-e2e coverage-gate validate pre-commit-setup pre-commit-run clean compose-up compose-down

help: ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ============================================================================
# Test Commands
# ============================================================================

# Use .venv/bin/pytest if available, fall back to system pytest.
# The .venv avoids the pytest-bdd compatibility issue on macOS system Python.
PYTEST = $(shell [ -f .venv/bin/pytest ] && echo ".venv/bin/pytest" || echo "pytest")

test: test-unit ## Run all tests
	@echo "All tests passed"

test-unit: ## Run unit tests (fast, no Docker)
	$(PYTEST) tests/unit/ -v --tb=short

test-coverage: ## Run tests with coverage report (unit tests only)
	$(PYTEST) tests/unit/ -v --tb=short --cov=compute --cov=ingestion --cov-report=term-missing

test-integration: ## Run integration tests (requires Docker)
	DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" $(PYTEST) tests/integration/ -v --tb=short -W error::RuntimeWarning

test-all: test-unit test-integration ## Run all tests (unit + integration)

coverage-gate: ## Run unit tests with coverage gate (80% min)
	$(PYTEST) tests/unit/ -v --tb=short \
		--cov=compute --cov=ingestion --cov-report=term-missing \
		--cov-fail-under=80

# ============================================================================
# Smoke / E2E Test Commands (requires Docker)
# ============================================================================

test-smoke: ## Run smoke tests against docker-compose.test.yml stack
	DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml up -d --build
	@echo "Waiting for API health..."
	@for i in $$(seq 1 20); do \
		if curl -s -o /dev/null -w '%{http_code}' http://localhost:8089/health 2>/dev/null | grep -q 200; then \
			echo "API ready (attempt $$i)"; \
			break; \
		fi; \
		sleep 3; \
	done
	@curl -s http://localhost:8089/health | python3 -c "import sys, json; d=json.load(sys.stdin); assert d.get('status') == 'ok', f'Expected ok, got {d}'"
	@echo "✅ Smoke test passed"
	@DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml down -v

test-e2e: ## Run E2E flow test against docker-compose.test.yml stack
	DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml up -d --build
	@echo "Waiting for E2E stack..."
	@for i in $$(seq 1 20); do \
		if curl -s -o /dev/null -w '%{http_code}' http://localhost:8089/health 2>/dev/null | grep -q 200; then \
			echo "API ready (attempt $$i)"; \
			break; \
		fi; \
		sleep 3; \
	done
	$(PYTEST) tests/integration/test_e2e_flow.py -v --tb=short
	@echo "✅ E2E test passed"
	@DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml down -v

compose-up: ## Start docker-compose.test.yml stack
	DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml up -d --build

compose-down: ## Tear down docker-compose.test.yml stack
	DOCKER_HOST="unix:///Users/philruff/.docker/run/docker.sock" \
	docker compose -f docker-compose.test.yml down -v

# ============================================================================
# Validation Commands
# ============================================================================

validate: pre-commit-run ## Validate all files (alias for pre-commit-run)

# ============================================================================
# Pre-commit Commands
# ============================================================================

pre-commit-setup: ## Install pre-commit hooks
	@pip install pre-commit
	@pre-commit install
	@echo "✅ Pre-commit hooks installed"

pre-commit-run: ## Run all pre-commit hooks
	@pre-commit run --all-files

# ============================================================================
# Database Commands (local dev with docker-compose.dev.yml)
# ============================================================================

db-up: ## Start local TimescaleDB for development
	docker compose -f docker-compose.dev.yml up -d

db-down: ## Stop local TimescaleDB
	docker compose -f docker-compose.dev.yml down

db-reset: db-down ## Recreate local TimescaleDB (down + remove volume + up)
	docker compose -f docker-compose.dev.yml down -v
	docker compose -f docker-compose.dev.yml up -d

db-psql: ## Connect to local TimescaleDB via psql
	@psql -h localhost -p 5432 -U postgres -d dora_metrics

db-logs: ## View TimescaleDB logs
	docker compose -f docker-compose.dev.yml logs -f

# ============================================================================
# Cleanup
# ============================================================================

clean: ## Clean up test artifacts
	rm -rf .pytest_cache __pycache__ tests/__pycache__ tests/unit/__pycache__
	rm -rf htmlcov .coverage coverage.xml
