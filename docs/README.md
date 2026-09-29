# 📚 Документация Smart Home Platform

Полная документация проекта организована по темам. Выбери интересующую тебя область:

## 🔌 Интеграция и API

| Документ | Описание |
|----------|---------|
| [device-integration-api.md](device-integration-api.md) | **REST API** для управления устройствами и источниками HA |
| [device-integration-examples.md](device-integration-examples.md) | **Примеры использования** API с curl и Python |
| [API-QUICK-REFERENCE.md](API-QUICK-REFERENCE.md) | **Краткая справка** по всем endpoints |
| [DEVICE_IMPORT_SPEC.md](DEVICE_IMPORT_SPEC.md) | **Спецификация** формата импорта устройств |

## 🏗️ Архитектура и Дизайн

Архитектурные решения документированы в [.ai/02_ARCHITECTURE.md](../.ai/02_ARCHITECTURE.md)

**Ключевые компоненты:**
- **Event-Driven FSM** — все устройства управляются через конечные автоматы
- **CommandDispatcher** — приоритизация и распределение команд
- **EventRouter** — маршрутизация событий сенсоров в FSM
- **Adapters** — интеграции с Home Assistant и другими системами

## 📋 Спецификации фич

**Device Integration (Phase 9)** — текущая работа:
- [spec.md](../specs/001-device-integration/spec.md) — требования
- [plan.md](../specs/001-device-integration/plan.md) — план реализации
- [tasks.md](../specs/001-device-integration/tasks.md) — список задач
- [data-model.md](../specs/001-device-integration/data-model.md) — модели данных

## 🚀 Быстрый старт

1. **Для разработчиков:** Прочитай [CLAUDE.md](../CLAUDE.md) → [.ai/00_START_HERE.md](../.ai/00_START_HERE.md)
2. **Для интеграции:** Начни с [API-QUICK-REFERENCE.md](API-QUICK-REFERENCE.md)
3. **Для понимания архитектуры:** [.ai/02_ARCHITECTURE.md](../.ai/02_ARCHITECTURE.md)

## 📖 Управление проектом

| Файл | Назначение |
|------|-----------|
| [.ai/01_PROJECT_STATE.md](../.ai/01_PROJECT_STATE.md) | Текущий статус, Known Issues |
| [.ai/03_ROADMAP.md](../.ai/03_ROADMAP.md) | План работ и статусы |
| [.ai/04_RULES.md](../.ai/04_RULES.md) | Жесткие ограничения разработки |
| [CHANGELOG.md](../CHANGELOG.md) | История изменений |

---

**Последнее обновление:** 2026-09-29
