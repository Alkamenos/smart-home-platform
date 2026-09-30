# Smart Home Management Platform — Инструкции для ИИ-ассистента

## 🚀 Точка входа

Перед началом ЛЮБОЙ работы:

1. **Прочитай конституцию проекта** → `.specify/memory/constitution.md` (v3.0.0)
2. **Изучи AI Context** → `.ai/00_START_HERE.md` (пошаговый workflow)
3. **Проверь состояние** → `.ai/01_PROJECT_STATE.md` (Known Issues)
4. **Запомни правила** → `.ai/04_RULES.md` (жесткие ограничения)

## 📋 Основные принципы

- **Язык:** Все файлы спецификаций, требования, планы задач и ответы оформляй исключительно на русском языке
- **Архитектура:** Event-Driven FSM (см. `.ai/02_ARCHITECTURE.md`)
- **Разработка:** TDD/SDD с AI-first подходом (см. конституцию v3.0.0)
- **Качество:** Pre-commit/pre-push хуки ВСЕГДА включены (см. `.ai/HOOKS.md`)
- **Workflow:** Следуй алгоритму из `.ai/00_START_HERE.md`

## 📁 Структура проекта

```
.
├── src/                      # Основной исходный код
│   ├── core/                 # Бизнес-логика (FSM, Dispatcher, EventRouter)
│   ├── adapters/             # Интеграции (Home Assistant, Mock)
│   ├── services/             # Вспомогательные сервисы (Metrics, Config Watcher)
│   └── webui/                # Web интерфейс
├── tests/                    # Тесты (unit, integration, E2E)
├── instances/                # Примеры конфигураций
├── docs/                     # Документация (единый вход — docs/README.md)
│   ├── guides/               # Гайды (вырезаны из README)
│   └── api/                  # REST API и спецификации
├── specs/                    # Спецификации фич (Spec Kit)
├── .ai/                      # Документация для ИИ-ассистента
│   ├── CONTEXT.md            # Индекс AI-контекста
│   ├── 00_START_HERE.md      # ← НАЧНИ ОТСЮДА ПЕРЕД КАЖДОЙ ЗАДАЧЕЙ
│   ├── 01_PROJECT_STATE.md   # Текущее состояние + Known Issues
│   ├── 02_ARCHITECTURE.md    # Архитектурные решения
│   ├── 03_ROADMAP.md         # План задач
│   ├── BACKLOG.md            # 📋 Единый пул задач (баги + фичи + стори)
│   ├── 04_RULES.md           # Жесткие ограничения
│   └── enhancements/         # Описания фич + INDEX.md (статусы)
├── .specify/                 # Spec Kit для управления спецификациями
│   └── memory/
│       └── constitution.md   # ← Конституция проекта v3.0.0
└── pyproject.toml            # Зависимости и конфиг

```

## 🎯 Что делать если...

- **Не знаешь с чего начать?** → Открыть `.ai/00_START_HERE.md`
- **Выбираешь следующую задачу?** → Открыть `.ai/BACKLOG.md` (единый пул: быстрые фиксы, фичи со стори, бэклог)
- **Нужен гайд или API?** → Открыть `docs/README.md` (индекс документации)
- **Нашел баг?** → Добавить в `.ai/01_PROJECT_STATE.md` → Known Issues
- **Нужно изменить код?** → Проверить `.ai/04_RULES.md` → не трогать без разрешения
- **Завершил задачу?** → Обновить `.ai/01_PROJECT_STATE.md` и запустить `python3 .ai/scripts/sync_roadmap.py --auto-update`

## 🔗 Полезные команды

```bash
# Запустить все проверки качества (обязательно перед коммитом!)
.ai/scripts/run_checks.sh

# Синхронизировать ROADMAP автоматически
python3 .ai/scripts/sync_roadmap.py --auto-update

# Запустить тесты с покрытием
pytest --cov=src tests/

# Быстрое исправление форматирования
ruff check --fix src/ tests/
ruff format src/ tests/

# Настроить git хуки
./.ai/scripts/setup_hooks.sh
```

## ⚠️ Критические правила

1. **Pre-commit хуки ВСЕГДА включены** — даже если отключишь их временно, при пуше они снова сработают
2. **Не коммитить если `run_checks.sh` падает** — исправить все проблемы, затем коммитить
3. **Манифест — единственный источник конфигурации** — никаких hardcoded значений в коде
4. **Core не импортирует Adapters** — архитектурное ограничение
5. **Все функции — type hints + docstrings** — без исключений
