# AGENTS.md

Инструкции для AI-ассистентов (OpenCode, Claude, ...). **Весь контекст проекта — в `CLAUDE.md`.**

## Точка входа

Перед началом любой работы:

1. `CLAUDE.md` — структура проекта, принципы, язык (русский)
2. `.specify/memory/constitution.md` — конституция проекта v3.0.0
3. `.ai/00_START_HERE.md` — пошаговый workflow задачи
4. `.ai/01_PROJECT_STATE.md` — текущее состояние и Known Issues
5. `.ai/04_RULES.md` — жёсткие ограничения

## Команды качества (всегда выполняй перед коммитом)

```bash
make lint        # ruff check
make format      # ruff format (OpenCode запускает его автоматически после правок)
make type-check  # mypy src/ — strict включён в pyproject.toml, флаг не нужен
make test        # pytest + coverage
```

То же через pre-commit: `pre-commit run --all-files`.

## Правила

- Ответы и артефакты спецификаций — на русском языке.
- TDD/SDD: сначала тесты и спецификация, потом реализация.
- Pre-commit/pre-push хуки не отключать (см. `.ai/HOOKS.md`).
- Источник истины по архитектуре — `.ai/02_ARCHITECTURE.md`.
