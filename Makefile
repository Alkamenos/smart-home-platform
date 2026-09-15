# Smart Home FSM Platform - Makefile

.PHONY: help test lint format clean install install-dev run-mock run-tests watch test-integration test-integration-verbose ai-setup ai-checks sync-roadmap changelog

# Default target
help:
	@echo "Smart Home FSM Platform - Available Commands"
	@echo ""
	@echo "Installation:"
	@echo "  make install       - Install production dependencies"
	@echo "  make install-dev   - Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests with coverage"
	@echo "  make test-verbose  - Run tests with verbose output"
	@echo "  make test-fast     - Run tests without coverage (faster)"
	@echo "  make test-integration - Run integration tests with real HA in Docker"
	@echo "  make watch         - Run tests in watch mode (auto-rerun on changes)"
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint          - Run linter (ruff/flake8)"
	@echo "  make format        - Format code with black"
	@echo "  make type-check    - Run type checking with mypy"
	@echo ""
	@echo "Development:"
	@echo "  make clean         - Remove build artifacts and cache"
	@echo "  make run-mock      - Run local mock simulator for debugging"
	@echo ""

# Installation
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pip install ruff black mypy pytest-watch

# Testing
test:
	pytest --cov=. --cov-report=term-missing --ignore=tests/integration/

test-verbose:
	pytest -v --cov=. --cov-report=term-missing --cov-report=html --ignore=tests/integration/

test-fast:
	pytest --no-cov

test-single:
	@if [ -z "$(FILE)" ]; then \
		echo "Usage: make test-single FILE=tests/test_fsm.py"; \
		exit 1; \
	fi
	pytest $(FILE) -v

watch:
	ptw --runner "pytest -x"

# Integration Tests
test-integration:
	@echo "Running integration tests with Home Assistant in Docker..."
	@echo ""
	@echo "Prerequisites:"
	@echo "  - Docker must be running"
	@echo "  - testcontainers-python must be installed: pip install testcontainers"
	@echo "  - websockets must be installed: pip install websockets"
	@echo ""
	pytest tests/integration/ -v --tb=short --timeout=0

test-integration-verbose:
	@echo "Running integration tests with verbose output..."
	pytest tests/integration/ -v -s --tb=long

# Code Quality
lint:
	ruff check src/ tests/

lint-fix:
	ruff check src/ tests/ --fix

format:
	black src/ tests/

type-check:
	mypy src/ --ignore-missing-imports

# Development
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type f -name ".coverage" -delete
	find . -type f -name "coverage.xml" -delete
	rm -rf htmlcov/ .mypy_cache/ dist/ build/ *.egg-info

run-mock:
	@echo "Starting Mock HA Simulator..."
	@echo "This simulates Home Assistant events for local testing."
	@echo ""
	python fsm_demo/kitchen_demo.py
	python fsm_demo/full_house_demo.py

# Alias for run-mock
run-simulator: run-mock

# Generate documentation
docs:
	@echo "Generating API documentation..."
	pdoc --html src/smart_home -o docs/api/ 2>/dev/null || echo "pdoc not installed, skipping API docs"
	@echo "Documentation generated in docs/api/"

# Build distribution
build:
	pip install build
	python -m build

# Verify package
verify:
	pip install twine
	twine check dist/*

# AI Harness targets
ai-setup:
	@echo "🤖 Setting up AI harness..."
	@mkdir -p .ai/scripts
	@chmod +x .ai/scripts/run_checks.sh
	@chmod +x .ai/scripts/sync_roadmap.py
	@echo "✅ AI harness ready"
	@echo ""
	@echo "Usage:"
	@echo "  make ai-checks      - Run all quality checks"
	@echo "  make sync-roadmap   - Sync roadmap from .ai/ to root"

ai-checks:
	@echo "🏥 Running quality checks..."
	@.ai/scripts/run_checks.sh

sync-roadmap:
	@echo "📊 Syncing roadmap..."
	@python .ai/scripts/sync_roadmap.py
	@echo "✅ ROADMAP.md updated"

# Changelog generation
changelog:
	@echo "📝 Generating changelog..."
	@python scripts/generate_changelog.py
	@echo "✅ CHANGELOG.md updated"
