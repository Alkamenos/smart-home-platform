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

## Документация (MCP)

Два локальных сервера документации, оба без VPN:

| Сервер | Что ищет | Инструменты |
|--------|----------|-------------|
| `docs` (docs-mcp-server) | Документация библиотек: pytest, home-assistant, pydantic проиндексированы | `docs.search_docs`, `docs.scrape_docs`, `docs.fetch_url` |
| `contextqmd` | Контекст проекта: `.ai/` (41 док, русский семантический поиск) | `contextqmd.search_docs`, `contextqmd.get_doc` |

Правила:

- **Перед поиском в интернете** — сначала `docs.search_docs`: индекс локальный и дешёвый для контекста.
- Библиотеки нет в индексе → `docs.list_libraries()`, потом один раз `docs.scrape_docs({library, url})`.
- Ответы по документации — со ссылками на источник (URL или `path:line`), без выдуманного API.
- Команда `/docs <запрос>` выполняет этот порядок автоматически.
- После правок `.ai/` векторный индекс ContextQMD устаревает → переиндексируй: `contextqmd.add_local_docs` + `contextqmd.embed_docs`.

## Правила

- Ответы и артефакты спецификаций — на русском языке.
- TDD/SDD: сначала тесты и спецификация, потом реализация.
- Pre-commit/pre-push хуки не отключать (см. `.ai/HOOKS.md`).
- Источник истины по архитектуре — `.ai/02_ARCHITECTURE.md`.
