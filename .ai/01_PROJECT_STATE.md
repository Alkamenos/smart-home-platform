# Project State

*Последнее обновление: 2026-09-19*

## 📌 Как использовать этот файл

**Перед началом задачи:** Проверь раздел "Known Issues" — нет ли связанных проблем.

**После завершения задачи:** Добавь запись в "Последние значимые изменения" и обнови статус.

---

**Версия:** v3.0.0 (Production Readiness)
**Последний коммит:** 2026-09-19 — feat(core): Add Secrets Management for secure credential handling

### ✅ Полностью реализовано и протестировано

| Компонент | Файл | Статус | Тесты |
|-----------|------|--------|-------|
| FSM Engine | `core/fsm.py` | ✅ Stable | `test_fsm.py`, `test_scheduler.py` |
| Command Dispatcher | `core/command_dispatcher.py` | ✅ Stable | `test_dispatcher.py` |
| Event Router | `core/event_router.py` | ✅ Stable | `test_event_router.py` |
| Middleware System | `core/middleware.py` | ✅ Stable | `test_middleware_integration.py` |
| Manifest Validation | `core/models/manifest.py` | ✅ Stable | `test_manifest_loading.py` |
| FSM Factory | `core/fsm_factory.py` | ✅ Stable | `test_composition_scenario.py` |
| Action Handlers | `core/action_handlers.py` | ✅ Stable | `test_action_handlers.py` |
| State Persistence | `core/state_persistence.py` | ✅ Stable | `test_persistence.py` |
| CLI | `cli.py` | ✅ Stable | `test_manifest_cli.py` |
| HA Adapter (WebSocket) | `adapters/ha_adapter.py` | ✅ Stable | `test_ha_adapter.py` |
| Mock Adapter | `adapters/mock_adapter.py` | ✅ Stable | `test_scenarios.py` |
| Room-Based Architecture | `bootstrap.py`, `core/` | ✅ New | Updated all tests |
| **Prometheus Metrics** | `core/metrics.py`, `services/metrics_server.py` | ✅ New | `test_metrics.py` |
| **Hot-Reload Service** | `services/config_watcher.py` | ✅ New | `test_hot_reload.py` |
| **Web UI** | `src/webui/app.py`, `src/webui/routes.py`, `src/webui/models.py` | ✅ New | `test_webui.py` |
| **FSM Visualization** | `src/core/fsm_visualizer.py`, `src/smart_home/cli/commands/export_fsm.py` | ✅ New | `test_fsm_visualizer.py` |
| **Interactive REPL** | `src/smart_home/cli/commands/shell.py`, `tests/test_shell.py` | ✅ New | `test_shell.py` |
| **Scene Manager** | `src/core/scene_manager.py`, `src/core/models/scene.py`, `tests/test_scene_manager.py` | ✅ New | `test_scene_manager.py` |
| **Room Aggregation & Policies** | `src/core/room_manager.py`, `src/core/models/room.py`, `tests/test_room_aggregation.py` | ✅ New | `test_room_aggregation.py` |
| **Secrets Management** | `src/core/secrets.py`, `tests/test_secrets.py` | ✅ New | `test_secrets.py` |

## Последние значимые изменения

### 2026-09-19 — Phase 9: Secrets Management ✅

**Задача:** Безопасное хранение токенов, паролей и чувствительных данных.

**Реализация:**
- `src/core/secrets.py` — модуль управления секретами
- `tests/test_secrets.py` — комплексные тесты (33 теста, 93% покрытие)

**Функциональность:**
- Резолвинг переменных окружения с синтаксисом `${VAR_NAME}`
- Поддержка значений по умолчанию: `${VAR_NAME:default_value}`
- Рекурсивная обработка nested структур (dict/list/tuple)
- Валидация манифестов на наличие plain-text секретов
- Опциональная загрузка `.env` файлов через python-dotenv
- Convenience функции: `resolve_secrets()`, `validate_secrets()`

**Интеграция:** Готово к использованию в manifest loader для безопасной подстановки секретов.

**Файлы:**
- `src/core/secrets.py` (новый)
- `tests/test_secrets.py` (новый)

**Статус:** ✅ Завершено, все проверки пройдены

---

### 🔴 Critical (Blocker для production)

1. **night_light не получает события движения**
   - **Файл:** `instances/leonids_house/manifest.yaml`
   - **Проблема:** В `night_light.params` отсутствует `motion_sensor`. EventRouter не строит маппинг для этого FSM.
   - **Статус:** Не исправлено

### 🟡 High

2. **EventRouter имеет жесткую связь с FSMEngine._definitions**
   - **Файл:** `core/event_router.py:67`
   - **Статус:** **ИСПРАВЛЕНО** (2026-09-15) — EventRouter теперь использует public API вместо private field access

### 🟢 Low

3. **Нет тестов для WebSocket reconnect logic**
   - **Файл:** `adapters/ha_adapter.py`
   - **Статус:** Не исправлено

## Последние значимые изменения

| Дата | Изменение | Файлы | Статус |
|------|-----------|-------|--------|
| 2026-09-19 | Room Aggregation & Policies implementation (Phase 8) | `src/core/room_manager.py`, `src/core/models/room.py`, `tests/test_room_aggregation.py` | ✅ Complete |
| 2026-09-18 | Scene Manager / Flow Engine implementation (Phase 8) | `src/core/scene_manager.py`, `src/core/models/scene.py`, `tests/test_scene_manager.py` | ✅ Complete |
| 2026-09-18 | Interactive REPL implementation (Phase 7) | `src/smart_home/cli/commands/shell.py`, `tests/test_shell.py` | ✅ Complete |
| 2026-09-17 | FSM Visualization implementation (Phase 7) | `src/core/fsm_visualizer.py`, `src/smart_home/cli/commands/export_fsm.py`, `tests/test_fsm_visualizer.py` | ✅ Complete |
| 2026-09-17 | Web UI for manifest editing implementation | `src/webui/app.py`, `src/webui/routes.py`, `src/webui/models.py`, `tests/test_webui.py` | ✅ Complete |
| 2026-09-17 | Hot-reload without restart implementation | `services/config_watcher.py`, `tests/test_hot_reload.py` | ✅ Complete |
| 2026-09-16 | Prometheus metrics collection implementation | `core/metrics.py`, `tests/test_metrics.py` | ✅ Complete |
| 2026-09-15 | Room-based architecture implementation | `bootstrap.py`, `core/`, `tests/` | ✅ Complete |
| 2026-09-15 | Extract `extract_device_id()` helper | `core/` | ✅ Complete |
| 2026-09-15 | EventRouter public API refactor | `core/event_router.py` | ✅ Complete |
| 2026-09-15 | Pre-commit hooks setup | `.pre-commit-config.yaml` | ✅ Complete |
| 2026-09-13 | EventRouter интеграция с HAAdapter | `core/event_router.py`, `adapters/ha_adapter.py` | ✅ Complete |
| 2026-09-13 | Middleware система | `core/middleware.py`, `core/control_tracker.py` | ✅ Complete |
| 2026-09-13 | Манифест в новый формат | `instances/leonids_house/manifest.yaml` | ✅ Complete |
| 2026-09-13 | E2E тест композиции | `tests/test_composition_scenario.py` | ✅ Complete |

## Архитектурные изменения

### 2026-09-16: Prometheus Metrics Implementation
- Добавлен модуль сбора метрик `core/metrics.py`
- Реализован MetricsCollector для записи ключевых метрик платформы
- Метрики: FSM transitions, event latency, HA errors, middleware conflicts, command rejections, active FSM instances
- Graceful degradation при отсутствии prometheus_client
- Покрытие тестами: 98%

### 2026-09-15: Room-Based Architecture
- Добавлена поддержка комнат как логических группировок устройств
- Backward compatibility aliases: `devices`, `zones`
- Обновлены все тесты для новой архитектуры
- Улучшена инкапсуляция и устранено дублирование кода

## Следующие шаги

Смотрите `03_ROADMAP.md` для детального плана развития.
