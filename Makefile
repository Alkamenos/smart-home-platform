# Smart Home FSM Platform - Makefile

.PHONY: help test test-verbose test-fast test-browser run-webui run-webui-prod lint format clean install install-dev run-mock run-tests watch test-integration test-integration-verbose ai-setup ai-checks sync-roadmap changelog export-fsm export-fsm-mermaid export-fsm-graphviz visualize-fsm

# Default target
help:
	@echo "Smart Home FSM Platform - Available Commands"
	@echo ""
	@echo "Installation:"
	@echo "  make install       - Install production dependencies"
	@echo "  make install-dev   - Install development dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests with coverage (full suite)"
	@echo "  make test-verbose  - Run tests with verbose output + HTML report"
	@echo "  make test-fast     - Run tests without coverage (faster)"
	@echo "  make test-browser  - Run browser tests (separate: see note below)"
	@echo "  make test-integration - Run integration tests with real HA in Docker"
	@echo "  make watch         - Run tests in watch mode (auto-rerun on changes)"
	@echo ""
	@echo "  Note: browser tests (tests/test_webui_playwright.py) are excluded"
	@echo "  from the full suite because playwright sync API holds a running"
	@echo "  event loop and breaks subsequent async tests (Known Issue #13)."
	@echo ""
	@echo "Code Quality:"
	@echo "  make lint          - Run linter (ruff/flake8)"
	@echo "  make format        - Format code with black"
	@echo "  make type-check    - Run type checking with mypy"
	@echo ""
	@echo "Development:"
	@echo "  make clean         - Remove build artifacts and cache"
	@echo "  make run-mock      - Run local mock simulator for debugging"
	@echo "  make run-webui     - Start WebUI server (development mode)"
	@echo "  make run-webui-prod - Start WebUI server (production mode)"
	@echo ""
	@echo "FSM Visualization (Phase 7):"
	@echo "  make export-fsm MANIFEST=<path> [DEVICE=<id>] [FORMAT=mermaid|graphviz] [OUTPUT=<file>]"
	@echo "                         - Export FSM visualization from manifest"
	@echo "  make export-fsm-mermaid MANIFEST=<path> [DEVICE=<id>] [OUTPUT=<file>]"
	@echo "                         - Export FSM as Mermaid diagram"
	@echo "  make export-fsm-graphviz MANIFEST=<path> [DEVICE=<id>] [OUTPUT=<file>]"
	@echo "                         - Export FSM as Graphviz DOT file"
	@echo "  make visualize-fsm MANIFEST=<path> [DEVICE=<id>]"
	@echo "                         - Export FSM and open in browser (Mermaid)"
	@echo ""

# Installation
install:
	pip install -e .

install-dev:
	pip install -e ".[dev]"
	pip install ruff black mypy pytest-watch

# Testing
#
# Состав набора задаётся в одном месте — pyproject.toml ([tool.pytest] addopts).
# Собственный --ignore здесь означал бы второй источник правды о том, что
# запускается, и молча сокращал набор: прежнее исключение tests/integration/
# убирало 163 теста в 14 файлах (8.4% набора), нигде об этом не сообщая.
# Исключения с причинами перечислены в specs/009-test-coverage/contracts/verification-funnel.md.
#
# Браузерные тесты (tests/test_webui_playwright.py, 25 шт.) исключены из общего
# прогона: playwright sync API держит running event loop и ломает последующие
# async-тесты (Known Issue #13). Запускаются отдельной целью `make test-browser`.

test:
	pytest --cov=. --cov-report=term-missing

test-verbose:
	pytest -v --cov=. --cov-report=term-missing --cov-report=html

test-fast:
	pytest --no-cov

# Браузерные тесты — объявленное исключение, поэтому отдельной целью,
# а не молчаливым исчезновением из результата.
test-browser:
	pytest tests/test_webui_playwright.py -v --no-cov

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
	ruff format src/ tests/

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

# WebUI
# ASGI-цель -- фабрика create_app: модульного `app` в src/webui/app.py нет
# (он объявлен только в src/main.py), поэтому прежняя цель `src.webui.app:app`
# завершалась ошибкой «Attribute "app" not found» (BACKLOG B10).
run-webui:
	@echo "🌐 Starting WebUI server..."
	@echo "Open http://localhost:8000 in your browser"
	uvicorn src.webui.app:create_app --factory --reload --host 0.0.0.0 --port 8000

run-webui-prod:
	@echo "🌐 Starting WebUI server (production mode)..."
	uvicorn src.webui.app:create_app --factory --host 0.0.0.0 --port 8000 --workers 4

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

# FSM Visualization (Phase 7)
export-fsm:
	@if [ -z "$(MANIFEST)" ]; then \
		echo "Error: MANIFEST is required"; \
		echo "Usage: make export-fsm MANIFEST=<path> [DEVICE=<id>] [FORMAT=mermaid|graphviz] [OUTPUT=<file>]"; \
		exit 1; \
	fi
	@echo "📊 Exporting FSM visualization from $(MANIFEST)..."
	@shp export-fsm $(MANIFEST) \
		$(if $(DEVICE),--device $(DEVICE),) \
		$(if $(FORMAT),--format $(FORMAT),--format mermaid) \
		$(if $(OUTPUT),--output $(OUTPUT),)

export-fsm-mermaid:
	@if [ -z "$(MANIFEST)" ]; then \
		echo "Error: MANIFEST is required"; \
		echo "Usage: make export-fsm-mermaid MANIFEST=<path> [DEVICE=<id>] [OUTPUT=<file>]"; \
		exit 1; \
	fi
	@echo "🎨 Exporting FSM as Mermaid diagram from $(MANIFEST)..."
	@shp export-fsm $(MANIFEST) \
		$(if $(DEVICE),--device $(DEVICE),) \
		--format mermaid \
		$(if $(OUTPUT),--output $(OUTPUT),)

export-fsm-graphviz:
	@if [ -z "$(MANIFEST)" ]; then \
		echo "Error: MANIFEST is required"; \
		echo "Usage: make export-fsm-graphviz MANIFEST=<path> [DEVICE=<id>] [OUTPUT=<file>]"; \
		exit 1; \
	fi
	@echo "🔷 Exporting FSM as Graphviz DOT file from $(MANIFEST)..."
	@shp export-fsm $(MANIFEST) \
		$(if $(DEVICE),--device $(DEVICE),) \
		--format graphviz \
		$(if $(OUTPUT),--output $(OUTPUT),)

visualize-fsm:
	@if [ -z "$(MANIFEST)" ]; then \
		echo "Error: MANIFEST is required"; \
		echo "Usage: make visualize-fsm MANIFEST=<path> [DEVICE=<id>]"; \
		exit 1; \
	fi
	@echo "🌐 Exporting FSM and preparing for browser visualization..."
	@mkdir -p visualizations
	@if [ -n "$(DEVICE)" ]; then \
		OUTPUT_FILE="visualizations/fsm_diagram_$(DEVICE).mmd"; \
		shp export-fsm $(MANIFEST) --device $(DEVICE) --format mermaid --output $$OUTPUT_FILE; \
		echo "✅ Diagram saved to $$OUTPUT_FILE"; \
		echo "🚀 Opening in browser..."; \
		content=$$(cat $$OUTPUT_FILE); \
		url="https://mermaid.live/edit#base64=$$(echo -n "$$content" | base64 | tr -d '\n')"; \
		python3 -c "import webbrowser; webbrowser.open('$$url')"; \
	else \
		OUTPUT_FILE="visualizations/fsm_diagram_all.mmd"; \
		shp export-fsm $(MANIFEST) --format mermaid --output $$OUTPUT_FILE; \
		echo "✅ Diagram saved to $$OUTPUT_FILE"; \
		echo "🚀 Opening in browser..."; \
		content=$$(cat $$OUTPUT_FILE); \
		url="https://mermaid.live/edit#base64=$$(echo -n "$$content" | base64 | tr -d '\n')"; \
		python3 -c "import webbrowser; webbrowser.open('$$url')"; \
	fi
