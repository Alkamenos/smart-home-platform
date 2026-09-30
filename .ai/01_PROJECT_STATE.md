# Project State

*Последнее обновление: 2026-09-30*

## 📌 Как использовать этот файл

**Перед началом задачи:** Проверь раздел "Known Issues" — нет ли связанных проблем.

**После завершения задачи:** Добавь запись в "Последние значимые изменения" и обнови статус.

---

**Версия:** v3.0.0 (Production Readiness)
**Последний коммит:** c6efd3e (2026-09-30) — feat(devices): история операций — модель DeviceSyncEvent, JSON-персистентность и запись config/access/command (spec 005)

### ✅ Полностью реализовано и протестировано

| Компонент | Файл | Статус | Тесты |
|-----------|------|--------|-------|
| FSM Engine | `src/core/fsm/engine.py` | ✅ Stable | `test_fsm.py`, `test_scheduler.py` |
| Command Dispatcher | `src/core/commands/dispatcher.py` | ✅ Stable | `test_dispatcher.py` |
| Event Router | `src/core/events/event_router.py` | ✅ Stable | `test_event_router.py` |
| Middleware System | `src/core/commands/middleware.py` | ✅ Stable | `test_middleware_integration.py`, `test_middleware_manual_lockout.py` |
| Manifest Validation | `src/core/models/manifest.py`, `src/core/manifest_validator.py` | ✅ Stable | `test_manifest_validator.py`, `test_manifest_schema.py` |
| FSM Factory | `src/core/fsm/factory.py` | ✅ Stable | `test_fsm_factory.py` |
| Action Handlers | `src/core/action_handlers.py` | ✅ Stable | косвенно через `test_fsm.py` (выделенного теста нет) |
| State Persistence | `src/core/persistence/` | ✅ Stable | `test_persistence.py`, `test_state_persistence.py`, `test_fsm_persistence.py` |
| CLI (`shp`) | `src/smart_home/cli/main.py` | ✅ Stable | `test_shell.py`, `test_fsm_visualizer.py` |
| HA Adapter (WebSocket) | `src/adapters/ha_adapter.py` | ✅ Stable | `test_ha_adapter.py`, `test_circuit_breaker.py` |
| Mock Adapter | `src/adapters/mock_adapter.py` | ✅ Stable | косвенно (`test_container.py`, `test_bootstrap.py`) |
| Room-Based Architecture | `src/bootstrap.py`, `src/core/` | ✅ New | Обновлены все тесты |
| **Prometheus Metrics** | `src/core/metrics.py`, `src/services/metrics_server.py` | ✅ New | `test_metrics.py`, `test_prometheus_metrics.py` |
| **Hot-Reload Service** | `src/services/config_watcher.py` | ⚠️ Не подключён | `test_hot_reload_memory.py` (см. Known Issues #8) |
| **Web UI** | `src/webui/app.py`, `src/webui/routes/`, `src/webui/models.py` | ✅ New | `test_webui.py`, `test_webui_fsm_e2e.py` |
| **FSM Visualization** | `src/core/fsm_visualizer.py`, `src/smart_home/cli/commands/export_fsm.py` | ✅ New | `test_fsm_visualizer.py` |
| **Interactive REPL** | `src/smart_home/cli/commands/shell.py` | ✅ New | `test_shell.py` |
| **Scene Manager** | `src/core/scene_manager.py`, `src/core/models/scene.py` | ✅ New | `test_scene_manager.py` |
| **Room Aggregation & Policies** | `src/core/room_manager.py`, `src/core/models/room.py` | ✅ New | `test_room_aggregation.py` |
| **Secrets Management** | `src/core/secrets.py` | ✅ New | `test_secrets.py` |

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
   - **Файл:** `src/core/container.py` (`build()`), `instances/leonids_house/manifest.yaml`
   - **Реальная причина (уточнена 2026-09-29):** `Container.build()` создавал EventRouter **до** регистрации FSM → `_build_mapping()` видел 0 устройств → маппинг sensor→FSM пуст навсегда. Причина НЕ в отсутствии `params.motion_sensor` (EventRouter params не читает — строит маппинг из `room.sensors`).
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — регистрация FSM перенесена до создания EventRouter в `container.py::build()`, добавлен регресс-тест `tests/test_container.py::test_build_event_router_mapping_includes_registered_fsms`, добавлены `sensors.motion` для `living_room`/`bathroom` в манифесте. Проверено: маппинг строится для 10 сенсоров (было 0).

### 🟡 High

2. **EventRouter имеет жесткую связь с FSMEngine._definitions**
   - **Файл:** `core/event_router.py:67`
   - **Статус:** **ИСПРАВЛЕНО** (2026-09-15) — EventRouter теперь использует public API вместо private field access

3. **`pytest tests/` целиком не собирался (import file mismatch)**
   - **Файлы:** `tests/contract/test_access_control.py` и `tests/integration/test_access_control.py` — одинаковый basename, в каталогах тестов нет `__init__.py`
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q2 из BACKLOG) — `--import-mode=importlib` в `[tool.pytest.ini_options] addopts` (`pyproject.toml`); полный `pytest tests/` собирается и работает: **29 failed / 1354 passed / 9 skipped** (= сумма baseline-групп 15+10+4), группы отдельно — цифры baseline не изменились

4. **Падающие тесты (сверено с baseline HEAD через worktree — 2026-09-29)**
   - **root+unit: 15** — `tests/unit/test_cache.py` (5), `tests/unit/test_models.py` (3), `tests/unit/test_device_service.py` (1: `test_handle_state_change_with_malformed_data`), `tests/test_websocket_batcher.py` (3), `tests/test_discovery_classifier.py` (2), `tests/test_metrics.py` (1 — ✅ исправлено 2026-09-29: невалидный kwarg `help=` в `MetricsCollector.initialize()`)
   - **contract: 10 failed + 40 passed** (запуск совместно с integration теперь можно — Known Issue #3 закрыт 2026-09-30)
   - **integration: 4 failed** (`test_commands.py` 2, `test_state_sync.py` 2)
   - **playwright: 14** — `RuntimeError: Runner.run() cannot be called from a running event loop` (конфликт event loop → см. Known Issue #13: файл заражает loop'ом последующие async-тесты)
   - Все перечисленные падают и на baseline (HEAD `d1918d8`) — не регрессии
   - **Статус:** Не исправлено

6. **`validate_manifest()` несовместим с текущим форматом манифеста** *(найдено 2026-09-29 при чистке документации)*
   - **Файл:** `src/core/manifest_validator.py` (`_validate_structure`)
   - **Проблема:** валидатор ожидает секции `devices`/`zones` верхнего уровня, а текущий формат манифеста использует `rooms:` с вложенными устройствами — на валидном `instances/leonids_house/manifest.yaml` возвращал 2 ложные ошибки
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — `rooms` принят как канонический формат (структура/типы/форматы/логика), legacy `devices`/`zones` сохранён; реальный манифест валидируется с 0 ошибок; +11 тестов в `tests/test_manifest_validator.py::TestRoomsFormat`

### 🟢 Low

5. **Нет тестов для WebSocket reconnect logic**
   - **Файл:** `adapters/ha_adapter.py`
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — `tests/test_ha_adapter_reconnect.py` (6 тестов: обрыв listen-задачи, исключение listen, backoff 1→2→4…≤60с, shutdown без висящих задач, метрика `websocket_disconnects_total`, WARNING/INFO contracts §4)

7. **Makefile-таргеты `export-fsm*` вызывают несуществующую команду `smart-home`** *(найдено 2026-09-29 при чистке документации)*
   - **Файл:** `Makefile` (строки ~172-191)
   - **Проблема:** в `pyproject.toml` entry point называется `shp`, поэтому `make export-fsm`, `make export-fsm-mermaid`, `make export-fsm-graphviz` падали с `command not found`
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — 5 вызовов `smart-home export-fsm` заменены на `shp export-fsm`, проверено `make -n` и `shp export-fsm --help`

### 🟡 High (добавлено 2026-09-29 при сверке расхождений)

8. **Hot-reload сервис не подключён к приложению**
   - **Файл:** `src/services/config_watcher.py`
   - **Проблема:** `ConfigWatcher` реализован (manifest + Python module reload), но нигде не инстанцируется (grep по `src/`: 0 вызовов вне самого файла) — hot-reload не работает при штатном старте. Также `tests/test_hot_reload.py`, на который ссылается roadmap Phase 6, **не существует** (есть только `test_hot_reload_memory.py` — тесты unregister/памяти FSM)
   - **Статус:** Не исправлено (roadmap Phase 6 помечен с предупреждением)

11. **US4 Access Control не подключён — права фактически не проверяются** *(найдено 2026-09-29 при сверке specs/001)*
   - **Файлы:** `src/webui/middleware_access_control.py` (не подключён), `src/webui/routes/devices/devices.py:79-82` (фильтрация закомментирована), `src/webui/routes/devices/websocket.py:158-174` (проверка закомментирована), `src/webui/routes/devices/access_control.py:104-206` (grant/revoke/list — заглушки)
   - **Проблема:** `DeviceAccessMiddleware` создан, но нигде не зарегистрирован; проверки доступа на device-endpoints отключены; эндпоинты выдачи прав возвращают заглушки (`UUID(int=0)`, `[]`)
   - **Бэклог:** Technical Debt → High Priority в `03_ROADMAP.md`, `specs/001-device-integration/tasks.md` → «Бэклог»
   - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — specs/004-device-access-control: middleware зарегистрирован в `create_app` (+`access_control.router` не был включён вовсе — 404), фильтрация `GET /api/v1/devices` по `get_user_accessible_devices`, grant/revoke/list на body-схемах с реальной логикой (grant device-blind), WS-подписка с `check_device_access` + доставка по правам при каждой доставке; module-level `app` в `src/main.py`; contract access 11 passed, integration access 2 passed. Отклонение: `grant_access` не требует существования устройства (grant до синка)

### 🟢 Low (добавлено 2026-09-29 при сверке расхождений)

9. **Канал доставки `params.motion_sensor` мёртв**
   - **Файлы:** `src/adapters/ha_adapter.py:300`, `src/core/fsm/factory.py:399`
   - **Проблема:** `HAAdapter` публикует `state_change` на `engine.event_bus`, но у `FSMEngine` такого атрибута нет → ветка уходит в `engine.trigger()` по несуществующему entity → подписка `_subscribe_to_sensor_events` никогда не срабатывает, даже если `motion_sensor` указан в params. Штатная доставка идёт через EventRouter (room sensors) — после фикса #1 работает
   - **Статус:** Не исправлено (мёртвый код, избыточный канал)

10. **MockAdapter не маршрутизирует state change события**
    - **Файл:** `src/adapters/mock_adapter.py:158-165`
    - **Проблема:** `set_event_router()` сохраняет роутер в `_event_router`, поле больше нигде не используется → в mock-режиме (без HA_TOKEN) motion-события не доставляются FSM
    - **Статус:** Не исправлено (влияет только на демо/mock-сценарии)

12. **`Task was destroyed but it is pending` при остановке контейнера** *(найдено 2026-09-29 при T011)*
    - **Файл:** контейнер `behavioral-platform`, uvicorn `Server.shutdown()` (Task-169)
    - **Проблема:** при `docker compose stop` event loop закрывается с pending-задачей self-shutdown uvicorn; критерии T011 (`Traceback`/`Unclosed client session`, останов ≤30с) при этом выполняются (останов 1с, 0 ошибок)
    - **Статус:** Не исправлено (низкий приоритет, косметика graceful shutdown)

### 🟡 High (добавлено 2026-09-30 при регрессе specs/005)

13. **`tests/test_webui_playwright.py` заражает event loop'ом весь root-прогон**
    - **Файл:** `tests/test_webui_playwright.py` (async-тесты с playwright `page`)
    - **Проблема:** session-фикстура playwright sync API (`playwright/sync_api/_context_manager.py:55` — `loop.run_until_complete(run_as_sync())` внутри greenlet) держит event loop в состоянии **running на протяжении всей pytest-сессии** после первой playwright-фикстуры → все последующие async-тесты падают с `RuntimeError: Runner.run() cannot be called from a running event loop`; даже синхронный тест с `asyncio.run()` после него падает. В root-прогоне под удар попадали: все 14 playwright-тестов (они были `async def` — конфликт sync API), ~51 `test_device_service.py`, 9 `test_device_sync_persistence.py` (specs/005) и др.
    - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q1 из BACKLOG) — (1) 14 тестов переведены на **sync API** (`def` без `await` — pytest-playwright предоставляет sync `page`), (2) файл исключён из общего прогона: `--ignore=tests/test_webui_playwright.py` в `[tool.pytest.ini_options] addopts` (`pyproject.toml`), запуск отдельно: `pytest tests/test_webui_playwright.py` (документировано в шапке файла). Проверено: root-прогон **15 failed / 1301 passed = baseline** (было 87), `run_checks.sh` exit 0
    - **Остаток (отдельная задача Q6 в BACKLOG):** отдельный прогон playwright зависит на teardown-сессии (stop_sync); часть ассертов устарела (`/health` отдаёт JSON `{"status":"ok"}`, а тест ищет "healthy")

## Последние значимые изменения

| Дата | Изменение | Файлы | Статус |
|------|-----------|-------|--------|
| 2026-09-30 | Q2 (BACKLOG): убран import file mismatch — `--import-mode=importlib` в pytest addopts (коллизия basename `test_access_control.py` в contract/integration); полный `pytest tests/` теперь собирается и работает: 29 failed / 1354 passed / 9 skipped (= сумма baseline-групп), группы отдельно без изменений; Known Issue #3 закрыт | `pyproject.toml` | ✅ Complete |
| 2026-09-30 | Q1 (BACKLOG): устранено loop-заражение playwright-файла — 14 E2E-тестов переведены на sync playwright API (были `async def` → конфликт с sync session-фикстурой, держащей running loop), файл исключён из общего прогона (`--ignore` в addopts), запуск отдельно; root-прогон: было 87 failed → **15 failed / 1301 passed = baseline**; Known Issue #13 закрыт (остаток — Q6: teardown-зависание отдельного прогона) | `tests/test_webui_playwright.py`, `pyproject.toml` | ✅ Complete |
| 2026-09-30 | Specs 005 device-audit-log: модель `DeviceSyncEvent` + `DeviceSyncEventPersistence` (append-only JSON `data/device_sync_events.json`), чтение `GET /api/v1/devices/{id}/events` из персистентности вместо заглушки, синхронная запись в webui-хендлерах (config_changed с before/after только запрашиваемых полей, access_granted/updated/revoked, command_executed с содержимым команды), helper `record_sync_event`/`get_sync_history` в deps; ТР-010 (Tech Debt High #2) закрыт; quickstart 6/6; регресс: contract/integration без новых падений, root без новых падений (9 падений unit — pre-existing заражение playwright, см. Known Issue #13) | `src/core/models/device_sync_event.py`, `src/core/persistence/{devices,manager}.py`, `src/webui/routes/devices/{deps,devices,access_control}.py`, `tests/unit/test_device_sync_{event,persistence}.py`, `tests/contract/test_device_events_api.py`, `tests/integration/test_device_audit_log.py`, `specs/005-device-audit-log/` | ✅ Complete |
| 2026-09-29 | Specs 004 US4 Access Control: DeviceAccessMiddleware зарегистрирован в create_app (+`access_control.router` не был включён — 404 на все access-endpoints), module-level `app` в main.py (TestClient-совместимость), фильтрация `GET /api/v1/devices` по доступу, grant/revoke/list на body-схемах с реальной логикой (grant device-blind), union-схема POST /command (стаб `cmd_123` удалён), WS: подписка с `check_device_access` + доставка по правам при каждой доставке; access contract 11 passed, integration 2 passed; регресс без новых падений | `src/webui/app.py`, `src/webui/middleware_access_control.py`, `src/webui/routes/devices/{devices,access_control,websocket,__init__}.py`, `src/webui/routes/devices/deps.py`, `src/services/device_service.py`, `src/main.py`, `tests/contract/test_access_control.py`, `tests/integration/test_access_control.py`, `tests/contract/{test_devices_api,test_sources_api}.py` | ✅ Complete |
| 2026-09-29 | Specs 003 US3: TTL командных интентов — `CommandIntent.last_updated/ttl_seconds` (+`refresh()/is_expired()`, валидация ≥0), `asyncio.Lock` в submit/cleanup, cleanup-loop (`start()/stop()` идемпотентны), force-release WARNING contracts §4, preempt-лог; lifecycle: `dispatcher.start()` в `Container.build()`, `PlatformContext.shutdown()` → `ctx.shutdown()` в `src/main.py`; тесты TTL (10) + регресс SC-005; фул-регресс без новых падений | `src/core/commands/dispatcher.py`, `src/core/container.py`, `src/main.py`, `tests/test_dispatcher_ttl.py`, `tests/test_dispatcher.py` | ✅ Complete |
| 2026-09-29 | Specs 003 US1+US2: healthcheck CLI+`/health` JSON, Docker E2E (10 мин healthy, 0 рестартов, stop 1с/без Traceback), WebSocket reconnect (backoff после обрыва, метрика `websocket_disconnects_total`, логи contracts §4), reconnect-тесты (6), фикс `MetricsCollector.initialize()` (13× `help=` → TypeError → все метрики были no-op) | `src/cli/health_check.py`, `src/webui/routes/__init__.py`, `src/adapters/ha_adapter.py`, `src/core/metrics.py`, `tests/test_ha_adapter_reconnect.py`, `tests/cli/`, `deploy/docker/Dockerfile`, `specs/003-critical-production-fixes/tasks.md` | ✅ Complete |
| 2026-09-29 | Устранение расхождений документации и кода: (1) motion-баг — EventRouter строил маппинг до регистрации FSM (порядок в `Container.build()`, регресс-тест, `sensors.motion` в living_room/bathroom); (2) `specs/001/tasks.md` — честная сверка 88/130 с бэклогом; (3) валидатор принимает `rooms`; (4) Makefile `shp`; (5) roadmap: secrets/hot-reload/цифры команд; (6) WebUI: путь шаблонов `routes/__init__.py` (`/health`, `/dashboard` отдавали 500 — TemplateNotFound) + изоляция тестов от реального манифеста (`test_webui.py` перезаписывал `instances/leonids_house/manifest.yaml` через `/devices/save`) | `src/core/container.py`, `tests/test_container.py`, `instances/leonids_house/manifest.yaml`, `specs/001-device-integration/tasks.md`, `src/core/manifest_validator.py`, `tests/test_manifest_validator.py`, `src/webui/routes/__init__.py`, `tests/test_webui.py`, `Makefile`, `.ai/03_ROADMAP.md` | ✅ Complete |
| 2026-09-29 | Реорганизация документации: README сокращён 1105 → 189 строк, гайды перенесены в `docs/guides/` (10 шт.), API — в `docs/api/`, удалены 6 отчётов-однодневок из корня, добавлен `.ai/enhancements/INDEX.md` | `README.md`, `docs/`, `.ai/enhancements/INDEX.md`, `.ai/CONTEXT.md`, `CLAUDE.md` | ✅ Complete |
| 2026-09-29 | Асинхронная публикация событий устройств (4 ошибки mypy unused-coroutine) + миграция `@validator` → `@field_validator` | `src/services/device_service.py`, `src/core/models/device_command.py`, `tests/unit/test_device_service.py` | ✅ Complete |
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
