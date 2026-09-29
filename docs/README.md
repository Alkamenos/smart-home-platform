# 📚 Документация Smart Home Platform

Единый вход в документацию проекта. Выбери интересующую тебя область:

## 🚀 Быстрые ссылки

- **Новичок или разработчик?** Начни с [../README.md](../README.md) → таблица гайдов в разделе Documentation
- **Интеграция / API?** → [api/quick-reference.md](api/quick-reference.md)
- **Для ИИ-ассистента?** → [../.ai/00_START_HERE.md](../.ai/00_START_HERE.md)

## 🧭 Гайды (`guides/`)

| Гайд | Описание |
|------|----------|
| [quickstart-add-devices.md](guides/quickstart-add-devices.md) | Импорт 200+ устройств из Home Assistant (CLI, Web UI, API) |
| [fsm-visualization.md](guides/fsm-visualization.md) | Экспорт диаграмм FSM в Mermaid / Graphviz |
| [manifest-examples.md](guides/manifest-examples.md) | Примеры манифеста: композиция поведений, middleware, миграции |
| [adding-behavior.md](guides/adding-behavior.md) | Как создать и зарегистрировать новый шаблон поведения |
| [trace-ids.md](guides/trace-ids.md) | Сквозная отладка событий по trace_id |
| [migration-v2-to-v3.md](guides/migration-v2-to-v3.md) | Миграция конфигураций v2.x → v3.0.0 |
| [local-development.md](guides/local-development.md) | Локальная разработка: тесты, линтинг, проверки |
| [ha-adapter-modes.md](guides/ha-adapter-modes.md) | Режимы адаптера: Pyscript vs WebSocket |
| [advanced-features.md](guides/advanced-features.md) | Manual override, debounce, цепочки таймаутов |
| [monitoring-debugging.md](guides/monitoring-debugging.md) | Конфигурация логов, поиск по trace_id |

## 🔌 API и спецификации (`api/`)

| Документ | Описание |
|----------|----------|
| [quick-reference.md](api/quick-reference.md) | **Краткая справка** по всем endpoints |
| [device-integration-api.md](api/device-integration-api.md) | **REST API** для управления устройствами и источниками HA |
| [device-integration-examples.md](api/device-integration-examples.md) | **Примеры использования** API с curl и Python |
| [device-import-spec.md](api/device-import-spec.md) | **Спецификация** формата импорта устройств |

## 🏗 Архитектура

Архитектурные решения документированы в [../.ai/02_ARCHITECTURE.md](../.ai/02_ARCHITECTURE.md)

**Ключевые компоненты:**
- **Event-Driven FSM** — все устройства управляются через конечные автоматы
- **CommandDispatcher** — приоритизация и распределение команд
- **EventRouter** — маршрутизация событий сенсоров в FSM
- **Adapters** — интеграции с Home Assistant и другими системами

## 📋 Спецификации фич

Рабочие спецификации (Spec Kit) лежат в [../specs/](../specs/):

- **Device Integration (Phase 9)** — [spec](../specs/001-device-integration/spec.md) · [plan](../specs/001-device-integration/plan.md) · [tasks](../specs/001-device-integration/tasks.md) · [data-model](../specs/001-device-integration/data-model.md)

Бэклог предложений по развитию — в [../.ai/enhancements/INDEX.md](../.ai/enhancements/INDEX.md)

## 📖 Управление проектом

| Файл | Назначение |
|------|-----------|
| [../.ai/01_PROJECT_STATE.md](../.ai/01_PROJECT_STATE.md) | Текущий статус, Known Issues |
| [../.ai/03_ROADMAP.md](../.ai/03_ROADMAP.md) | План работ и статусы |
| [../ROADMAP.md](../ROADMAP.md) | Человекочитаемый roadmap (генерируется) |
| [../.ai/04_RULES.md](../.ai/04_RULES.md) | Жесткие ограничения разработки |
| [../CHANGELOG.md](../CHANGELOG.md) | История изменений |
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Участие в проекте |

---

**Последнее обновление:** 2026-09-29
