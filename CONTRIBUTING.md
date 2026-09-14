# Contributing to Smart Home FSM Platform

Thank you for your interest in contributing to the Smart Home FSM Platform! This document provides guidelines and instructions for contributing to the project.

## 📋 Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Code Style](#code-style)
- [Testing](#testing)
- [Pull Request Process](#pull-request-process)

## Getting Started

### Prerequisites

- Python 3.10 or higher
- Git
- pip or poetry for dependency management

### Setting Up Development Environment

1. **Fork the repository** on GitHub

2. **Clone your fork:**
   ```bash
   git clone git@github.com:your-username/smart-home-platform.git
   cd smart-home-platform
   ```

3. **Create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

4. **Install development dependencies:**
   ```bash
   make install-dev
   ```

5. **Verify setup:**
   ```bash
   make test-fast
   ```

## Development Workflow

### Branch Naming

Use descriptive branch names following this pattern:
```
<type>/<description>
```

Where type is:
- `feat` - New feature
- `fix` - Bug fix
- `refactor` - Code refactoring
- `docs` - Documentation changes
- `test` - Test additions or modifications
- `chore` - Maintenance tasks

Examples:
- `feat/event-router-integration`
- `fix/manifest-validation-error`
- `refactor/fsm-engine-cleanup`

### Commit Messages

This project follows [Conventional Commits](https://www.conventionalcommits.org/) specification:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat` - Новая функциональность
- `fix` - Исправление багов
- `refactor` - Рефакторинг кода
- `docs` - Изменения документации
- `test` - Добавление тестов
- `chore` - Обслуживание (зависимости, конфиги)
- `ci` - Изменения CI/CD

**Правила:**
- Сообщение на русском языке
- Одна задача = один коммит (атомарность)
- Без эмодзи в коде
- Первая буква в описании строчная
- Точка в конце не ставится

**Примеры:**
```
feat: добавить middleware систему
fix(manifest): исправить валидацию priority
refactor: упростить логику event router
docs: обновить README с примерами
test: добавить тесты для composition pattern
```

### Making Changes

1. **Create a branch:**
   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes** following the code style guidelines

3. **Run tests:**
   ```bash
   make test
   ```

4. **Run linters:**
   ```bash
   make lint
   make format
   ```

5. **Commit your changes:**
   ```bash
   git add .
   git commit -m "feat: description of your change"
   ```

6. **Push to your fork:**
   ```bash
   git push origin feat/your-feature-name
   ```

## Code Style

### Formatting

The project uses **Black** for code formatting with line length of 100 characters:

```bash
make format
```

Configuration in `pyproject.toml`:
```toml
[tool.black]
line-length = 100
target-version = ['py310', 'py311', 'py312']
```

### Import Sorting

Imports are sorted using **isort** with black profile:

```bash
isort --profile black src/ tests/
```

### Type Hints

**Type hints are mandatory everywhere.** Use Python 3.10+ syntax:

```python
from typing import Optional, Any
from pydantic import BaseModel

class DeviceConfig(BaseModel):
    id: str
    name: str
    behaviors: list[dict[str, Any]]
    
async def process_event(event: dict[str, Any]) -> Optional[str]:
    ...
```

### Linting

The project uses **Ruff** for linting:

```bash
make lint
```

Fix issues automatically when possible:
```bash
ruff check --fix src/ tests/
```

### Logging

Use **loguru** for logging:

```python
from loguru import logger

logger.info("Processing event: {event}", event=event_name)
logger.error("Failed to process: {error}", error=str(e))
```

## Testing

### Running Tests

```bash
# All tests with coverage
make test

# Fast test run without coverage
make test-fast

# Single test file
make test-single FILE=tests/test_fsm.py

# Watch mode (auto-rerun on changes)
make watch
```

### Writing Tests

Tests use **pytest** with **pytest-asyncio** for async tests:

```python
import pytest
from src.smart_home.core.fsm import FSMEngine

@pytest.mark.asyncio
async def test_state_transition():
    engine = FSMEngine()
    # Setup
    engine.register_state("idle")
    engine.register_state("active")
    
    # Exercise
    await engine.trigger("device_1", "motion_detected")
    
    # Verify
    state = engine.get_state("device_1")
    assert state.current_state == "active"
```

### Test Coverage

Aim for high test coverage, especially for:
- Core FSM engine logic
- Guard conditions
- Action handlers
- Middleware components
- Edge cases and error handling

### Integration Tests

For integration tests with Home Assistant:
```bash
make test-integration
```

Requires Docker and homeassistant-websocket package.

## Pull Request Process

### Before Submitting

1. **Ensure all tests pass:**
   ```bash
   make test
   ```

2. **Check code quality:**
   ```bash
   make lint
   make format
   ```

3. **Update documentation** if you changed functionality

4. **Add tests** for new features or bug fixes

5. **Update CHANGELOG.md** in the [Unreleased] section

### PR Title

Use conventional commits format:
```
feat: добавить поддержку новых сенсоров
fix: исправить гонку в event dispatcher
refactor: оптимизировать работу scheduler
```

### PR Description

Use the following template:

```markdown
## Описание
Краткое описание изменений

## Тип изменений
- [ ] ✨ Новая функция (feat)
- [ ] 🐛 Исправление бага (fix)
- [ ] ♻️ Рефакторинг (refactor)
- [ ] 📝 Документация (docs)
- [ ] ✅ Тесты (test)
- [ ] 🔧 Конфигурация (chore)

## Чеклист
- [ ] Код отформатирован (black)
- [ ] Импорты отсортированы (isort)
- [ ] Линтер не находит ошибок (ruff)
- [ ] Все тесты проходят
- [ ] Добавлены тесты для новых функций
- [ ] Обновлена документация
- [ ] Обновлен CHANGELOG.md

## Скриншоты (если применимо)
...

## Related Issues
Closes #123
```

### Review Process

1. Maintainers will review your PR
2. Address any feedback or requested changes
3. Once approved, your PR will be merged

### After Merge

- Delete your feature branch
- Update your local main branch:
  ```bash
  git checkout main
  git pull origin main
  ```

## 📚 Additional Resources

- [Python Documentation](https://docs.python.org/3/)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/)
- [pytest Documentation](https://docs.pytest.org/)
- [Black Documentation](https://black.readthedocs.io/)
- [Conventional Commits](https://www.conventionalcommits.org/)

## ❓ Questions?

Open an issue with the `question` label or join discussions in existing issues.
