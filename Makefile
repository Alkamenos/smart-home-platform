# Smart Home FSM Platform - Makefile

.PHONY: help test lint format clean install install-dev run-mock run-tests watch

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
	pytest --cov=. --cov-report=term-missing

test-verbose:
	pytest -v --cov=. --cov-report=term-missing --cov-report=html

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

# Code Quality
lint:
	ruff check src/ tests/ examples/

format:
	black src/ tests/ examples/

type-check:
	mypy src/ --ignore-missing-imports

# Development
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type d -name "*.pyc" -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -exec rm -rf {} +
	find . -type d -name ".coverage" -exec rm -rf {} +
	find . -type f -name "coverage.xml" -exec rm -f {} +
	rm -rf htmlcov/
	rm -rf .mypy_cache/
	rm -rf dist/
	rm -rf build/
	rm -rf *.egg-info

run-mock:
	@echo "Starting Mock HA Simulator..."
	@echo "This simulates Home Assistant events for local testing."
	@echo ""
	python examples/kitchen_demo.py

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
