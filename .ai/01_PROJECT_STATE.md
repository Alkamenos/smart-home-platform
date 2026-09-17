# Project State

*Последнее обновление: 2026-09-17*

## Текущий статус

**Версия:** v3.0.0 (Production Readiness)
**Последний коммит:** 2026-09-17 — feat: implement hot-reload without restart (Phase 6)

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

## Known Issues

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
