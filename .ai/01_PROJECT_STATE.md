# Project State

**Последнее обновление:** 2026-09-14
**Версия платформы:** v3
**Текущая фаза:** Phase 4 — Production Readiness

## Что работает

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

### 🔄 В работе (не завершено)

| Задача | Статус | Описание |
|--------|--------|----------|
| Fix night_light manifest bug | 🔴 Critical | `night_light` params не содержит `motion_sensor`, EventRouter не роутит события |
| Clean legacy tests | 🟡 In Progress | Нужно удалить `test_legacy_*.py`, добавить новые проверки |
| Pre-commit hooks | 🟡 Planned | Настроить автоматические проверки перед коммитом |
| Migration docs | 🟡 Planned | `docs/MIGRATION_V2_TO_V3.md` |

## Known Issues

### 🔴 Critical (Blocker для production)

1. **night_light не получает события движения**
   - **Файл:** `instances/leonids_house/manifest.yaml`
   - **Проблема:** В `night_light.params` отсутствует `motion_sensor`. EventRouter не строит маппинг для этого FSM.
   - **Воспроизведение:** Запустить платформу в 23:30, эмулировать движение — свет не включится.
   - **Фикс:** Добавить `motion_sensor: binary_sensor.kitchen_motion` в params night_light.
   - **Связанная задача:** `03_ROADMAP.md` → Phase 4 → Fix manifest bug

### 🟡 High

2. **EventRouter имеет жесткую связь с FSMEngine._definitions**
   - **Файл:** `core/event_router.py:67`
   - **Проблема:** `_get_fsm_entity_ids_for_device()` обращается к приватному полю `_definitions`.
   - **Влияние:** Если изменится внутренняя структура FSMEngine, EventRouter сломается.
   - **Предложение:** Добавить публичный метод `engine.get_entities_by_device(device_id)`.

3. **Дублирование в action handlers**
   - **Файл:** `core/action_handlers.py`
   - **Проблема:** Каждая функция повторяет логику `context.get("target_device_id") or context.get("entity_id")...`
   - **Предложение:** Вынести в хелпер `extract_device_id(context)`.

### 🟢 Low

4. **Нет тестов для WebSocket reconnect logic**
   - **Файл:** `adapters/ha_adapter.py`
   - **Описание:** Логика экспоненциального бэкоффа не покрыта тестами.

## Технические метрики

- **Количество тестов:** ~150 (нужна точная цифра после очистки)
- **Покрытие кода:** ~85% (оценка)
- **Строк кода (без тестов):** ~3500
- **Количество модулей в core:** 12

## Последние значимые изменения

| Дата | Изменение | Файлы |
|------|-----------|-------|
| 2026-09-13 | EventRouter интеграция с HAAdapter | `core/event_router.py`, `adapters/ha_adapter.py` |
| 2026-09-13 | Middleware система | `core/middleware.py`, `core/control_tracker.py` |
| 2026-09-13 | Манифест в новый формат | `instances/leonids_house/manifest.yaml` |
| 2026-09-13 | E2E тест композиции | `tests/test_composition_scenario.py` |
