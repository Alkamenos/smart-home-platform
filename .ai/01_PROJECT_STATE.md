# Project State

*Последнее обновление: 2026-10-07*

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
| **Web UI** | `src/webui/app.py`, `src/webui/routes/`, `src/webui/models.py` | ✅ New | `test_webui.py`, `test_webui_playwright.py` (25 тестов). `test_webui_fsm_e2e.py` содержал 0 исполняемых тестов — см. Known Issue #27 |
| **FSM Visualization** | `src/core/fsm_visualizer.py`, `src/smart_home/cli/commands/export_fsm.py` | ✅ New | `test_fsm_visualizer.py` |
| **Interactive REPL** | `src/smart_home/cli/commands/shell.py` | ✅ New | `test_shell.py` |
| **Scene Manager** | `src/core/scene_manager.py`, `src/core/models/scene.py` | ✅ New | `test_scene_manager.py` |
| **Room Aggregation & Policies** | `src/core/room_manager.py`, `src/core/models/room.py` | ✅ New | `test_room_aggregation.py` |
| **Secrets Management** | `src/core/secrets.py` | ✅ New | `test_secrets.py` |

## Опорные числа тестов (baseline specs/009)

Зафиксировано 2026-10-03 на коммите `98b5f2c`, до начала фичи Verified Coverage.

| Метрика | Значение |
|---------|----------|
| Собрано тестов | **1786** |
| Выполнено | **1777** |
| Пропущено | **9** (все — сценарии спеки 001, помеченные `[x]`) |
| Упало | 0 |
| Время полного прогона | 85.48 с (pytest) / 86.84 с (wall clock) |
| Браузерные тесты (отдельно) | 25 passed |
| Покрытие | 92.9% |
| `run_checks.sh` | exit 0 |

**Состояние на 2026-10-03 после волн 0 и US1:** **1895 выполнено / 0 пропущено / 0 упало**. Пропуски сняты все девять: они оказались не «недоделанными задачами», а рассинхроном с API — 5 падений на отсутствующем `X-User-ID`, 1 на реальном сетевом соединении, 3 «проходили», пропуская себя сами.

**Побочный факт, измерено:** полный прогон **растит `data/sources.json` на 17 123 байта за запуск** — детерминированно, не шум: каждый запуск добавляет 31 запись со свежими UUID. В каталоге накопилось 2611+ источников и 2358 событий синхронизации — это не данные установки, а следы прошлых прогонов. Файлы в `.gitignore` (строка 223), поэтому рост не виден в `git status`. Источник — тесты контракта и интеграции, берущие синглтон `src.main.app`; изолированные фикстуры дают вклад **0 байт** (проверено сравнением с контрольным прогоном). Требует отдельной задачи — см. Known Issue #28.

**Дефекты покрытия, найденные сверкой с кодом** (реализуются в specs/009):

| Что | Где |
|-----|-----|
| Файл с 0 исполняемых тестов | `tests/test_webui_fsm_e2e.py` |
| 4 теста шифрования в файле, который pytest не собирает | `tests/security/verify_security.py` (имя не `test_*.py`, содержимое под `if __name__ == "__main__"`) |
| 755 строк командной строки без тестов | `src/smart_home/cli/commands/bulk_import.py`, `export_fsm.py` |
| ~~Локальная команда проверки исключает `tests/integration/`~~ **исправлено в specs/009** | `Makefile` против `pyproject.toml` |
| ~~Браузерные тесты не видны ни в одной проверке~~ **исправлено в specs/009** | исключены из `addopts`, добавлена цель `make test-browser` |
| ~~Локальная команда проверки не выполняла ни одного теста~~ **исправлено в specs/009** | `pythonpath` отсутствовал; console-script `pytest` падал на коллекции |
| ~~Скрипт проверки не запускал тесты и заявлял успех при их провале~~ **исправлено в specs/009** | `run_checks.sh`: блок закомментирован с 2026-09-21; `pytest | tail` терял код возврата |

## Последние значимые изменения

### 2026-10-03 — specs/009 US1: заявленное покрытие исполняется ✅

**Главный инвариант фичи достигнут: `skipped == 0`.** 1895 выполнено / 0 пропущено / 0 упало (было 1777 / 9 / 0). Плюс 5 коммитов: `6b3f5f5` (волна 0), `1ea5697`, `2a1453d`, `966a579`.

**Все девять пропусков оказались не «недоделанными задачами».** Измерение сняло их во временной копии и прогнало: 1 прошёл, 6 упали, 2 «прошли» тем, что пропускали себя сами (`pytest.skip` стоял **до** всякой проверки прав). Фактические причины — рассинхрон с API: 5 × 401 из-за отсутствующего `X-User-ID` (middleware из specs/004 исключает ровно два маршрута), 1 × 500 из-за реального TCP-соединения с `192.168.1.100:8123`. Отметки `[x]` в `specs/001-device-integration/tasks.md` были ложными.

**Ловушка, которая сделала бы 6 тестов декоративными.** httpx **сливает** заголовки запроса с дефолтными заголовками клиента, а не заменяет их. Переопределение только `X-User-ID` оставляло `X-Is-Admin: true`, и пользователь с ролью `viewer` получал admin-bypass: 202 вместо 403. Проверка прав проходила, ничего не проверяя. Заведён хелпер `_as()`.

**Что ещё вскрыто:**

| Находка | Где |
|---------|-----|
| 40 тестов не проверяют результат; 5 из них с комментариями, признающими отсутствие проверки | Known Issue #29 |
| `test_ha_adapter.py:443` объявляет `failing_connect()`, **но ни разу её не вызывает** и заканчивается `pass` | Known Issue #29 |
| Голая `token` отсутствует в `SENSITIVE_PATTERNS` — проверка маскирования её пропускает | Known Issue #31 |
| Повышение роли **пересоздаёт** запись о доступе с новым идентификатором | `device_service.py:990-1000` |
| Утечка в журнал событий невидима при сканировании по размеру: `device_access.json` после revoke возвращался к исходному | `test_access_control.py` (исправлено) |

**Переписано под текущий контракт:** 3 + 3 + 3 интеграционных теста → 48 исполняемых. Перенесено в собираемые файлы 10 тестов, которые выполнялись, но были не видны ни в одной проверке. Удалён файл с нулём тестов.

**Побочный факт, не требующий действий:** ожидание «пропавшее устройство исчезает из списка» противоречит контракту specs/006 — исчезнувшие помечаются `removed_from_ha`, а не выбрасываются. Первая версия теста проверяла запрещённое поведение; исправлено на пометку и снятие автоматики.

### 2026-10-03 — specs/009 Verified Coverage: спека, план, задачи

**Задача:** привести заявленное покрытие в состояние, когда оно исполняется.

**Состояние:** спека (4 US, 26 FR, 17 SC), план с research (10 решений), data-model, контракт воронки проверок, quickstart (10 сценариев), 39 задач в 7 фазах. Реализация начата.

**Что установлено измерением** (снятие 9 пропусков во временной копии): 1 прошёл, 6 упали, 2 «прошли» тем, что пропускали себя сами. Ни один не упал на ошибке подготовки — падения рассинхрон с API, а не недоделанные TODO. Причины: 5 × 401 (отсутствует `X-User-ID`), 1 × 500 (реальное TCP-соединение), 2 × самопропуск до всякой проверки.

**Решение D-1:** 4 E2E-файла `test_device_*_e2e.py` не создаются — их сценарии уже покрыты более поздними и более сильными тестами. Исходная формулировка задачи F4 («0 из 6 E2E») при сверке с кодом оказалась неверной.

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


## Known Issues

Все записи в одном разделе, в порядке номеров. До 2026-10-07 они были
разбросаны: часть — нумерованные пункты внутри тематических блоков по
приоритету, часть — заголовки `###` ниже. Указатель был нужен именно
поэтому; теперь, когда раздел собран, он избыточен и удалён.

Приоритет вынесен в заголовок (`· Critical`, `· High`, `· Low`). Записи #80,
#81 и #82 жили только строками в указателе — они перенесены сюда, чтобы
перенос раздела не потерял их формулировки.

**Номер #78 занят дважды** — это две разные находки: разрыв сети (heartbeat)
и таймаут-переходы, не переживающие перезапуск. Номера не перенумеровываются,
потому что на них ссылаются записи и `BACKLOG.md`.

---


### #1 — night_light не получает события движения · Critical
- **Файл:** `src/core/container.py` (`build()`), `instances/leonids_house/manifest.yaml`
- **Реальная причина (уточнена 2026-09-29):** `Container.build()` создавал EventRouter **до** регистрации FSM → `_build_mapping()` видел 0 устройств → маппинг sensor→FSM пуст навсегда. Причина НЕ в отсутствии `params.motion_sensor` (EventRouter params не читает — строит маппинг из `room.sensors`).
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — регистрация FSM перенесена до создания EventRouter в `container.py::build()`, добавлен регресс-тест `tests/test_container.py::test_build_event_router_mapping_includes_registered_fsms`, добавлены `sensors.motion` для `living_room`/`bathroom` в манифесте. Проверено: маппинг строится для 10 сенсоров (было 0).


### #2 — EventRouter имеет жесткую связь с FSMEngine._definitions · High
- **Файл:** `core/event_router.py:67`
- **Статус:** **ИСПРАВЛЕНО** (2026-09-15) — EventRouter теперь использует public API вместо private field access


### #3 — `pytest tests/` целиком не собирался (import file mismatch) · High
- **Файлы:** `tests/contract/test_access_control.py` и `tests/integration/test_access_control.py` — одинаковый basename, в каталогах тестов нет `__init__.py`
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q2 из BACKLOG) — `--import-mode=importlib` в `[tool.pytest.ini_options] addopts` (`pyproject.toml`); полный `pytest tests/` собирается и работает: **29 failed / 1354 passed / 9 skipped** (= сумма baseline-групп 15+10+4), группы отдельно — цифры baseline не изменились


### #4 — Падающие тесты (сверено с baseline HEAD через worktree — 2026-09-29) · High
- **root+unit: 15** — `tests/unit/test_cache.py` (5), `tests/unit/test_models.py` (3), `tests/unit/test_device_service.py` (1: `test_handle_state_change_with_malformed_data`), `tests/test_websocket_batcher.py` (3), `tests/test_discovery_classifier.py` (2), `tests/test_metrics.py` (1 — ✅ исправлено 2026-09-29: невалидный kwarg `help=` в `MetricsCollector.initialize()`)
- **contract: 10 failed + 40 passed** (запуск совместно с integration теперь можно — Known Issue #3 закрыт 2026-09-30)
- **integration: 4 failed** (`test_commands.py` 2, `test_state_sync.py` 2)
- **playwright: 14** — `RuntimeError: Runner.run() cannot be called from a running event loop` (конфликт event loop → см. Known Issue #13: файл заражает loop'ом последующие async-тесты)
- Все перечисленные падают и на baseline (HEAD `d1918d8`) — не регрессии
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q4 из BACKLOG) — все 29 baseline-падений устранены: **полный прогон 1411 passed / 9 skipped / 0 failed**, `run_checks.sh` exit 0
  - **Код (реальные баги):** (1) `src/webui/app.py` — `sources.router` регистрировался после `devices.router`, и `GET /api/v1/devices/sources` перехватывался маршрутом `GET /api/v1/devices/{device_id}` → 422; (2) `src/services/device_service.py:_call_ha_service` — `result or {}` пропускало непустые не-dict значения (`True` от HAAdapter) → `ValidationError` при ответе (падало бы и в HA-режиме); (3) `src/core/persistence/index_manager.py:update_device` — алиасинг (`old_device is device` после мутации) оставлял устройство в старом индексе → теперь id вычищается из всех бакетов; (4) `src/core/models/device_config.py` / `device_command.py` — констрейнты `min_length=1`/`le=300` срабатывали раньше field-валидаторов и глушили кастомные сообщения; `CommandExecutionResponse.created_at` → `default_factory`; (5) `src/core/discovery/classifier.py` — `\b` не работал с `_`-сепараторами entity_id (`_` — словный символ regex), не было транслита `temperatura`, `vent` ≠ `ventilat` (fan без шаблона); добавлен `_searchable_text()`; (6) `src/webui/routes/devices/sources.py` — `HttpUrl` добавлял `/` в URL ответа (`rstrip("/")`), новый источник создавался со статусом `active` → `connected` вместо `disconnected`
  - **Тесты (устаревшие/некорректные):** импорт `_devices_store` через `src.webui...` создавал второй экземпляр модуля → 404 (`test_devices_api.py`, `test_device_config.py`); контрактный sync без мока HA → честный 500 (добавлен мок `connect_to_ha`/`fetch_devices`); websocket-тесты: не сконфигурирован `receive_json`, `__aiter__` вызывается с mock-объектом, батчинг меняет формат callback (`enable_batching=False`); `'id' in <pydantic model>` (v2) → `model_dump()`; формат события `state_changed` приведён к HA-envelope; `grant_access` — тест обновлён под документированный device-blind grant (specs/004); убран противоречивый `pytest.raises` в malformed-тесте; невалидные `ha_entity_id` без точки в `test_cache.py` (падение в тредах → 0 устройств); LRU-тест заполнял кэш на 9 из 10 (вытеснение не срабатывало); батчер-тесты создают локальные инстансы (фикстура `limit=3` вызывала автосрабатывание по размеру)


### #5 — Нет тестов для WebSocket reconnect logic · Low
- **Файл:** `adapters/ha_adapter.py`
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — `tests/test_ha_adapter_reconnect.py` (6 тестов: обрыв listen-задачи, исключение listen, backoff 1→2→4…≤60с, shutdown без висящих задач, метрика `websocket_disconnects_total`, WARNING/INFO contracts §4)


### #6 — `validate_manifest()` несовместим с текущим форматом манифеста · High
*(найдено 2026-09-29 при чистке документации)*
- **Файл:** `src/core/manifest_validator.py` (`_validate_structure`)
- **Проблема:** валидатор ожидает секции `devices`/`zones` верхнего уровня, а текущий формат манифеста использует `rooms:` с вложенными устройствами — на валидном `instances/leonids_house/manifest.yaml` возвращал 2 ложные ошибки
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — `rooms` принят как канонический формат (структура/типы/форматы/логика), legacy `devices`/`zones` сохранён; реальный манифест валидируется с 0 ошибок; +11 тестов в `tests/test_manifest_validator.py::TestRoomsFormat`


### #7 — Makefile-таргеты `export-fsm*` вызывают несуществующую команду `smart-home` · Low
*(найдено 2026-09-29 при чистке документации)*
- **Файл:** `Makefile` (строки ~172-191)
- **Проблема:** в `pyproject.toml` entry point называется `shp`, поэтому `make export-fsm`, `make export-fsm-mermaid`, `make export-fsm-graphviz` падали с `command not found`
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — 5 вызовов `smart-home export-fsm` заменены на `shp export-fsm`, проверено `make -n` и `shp export-fsm --help`


### #8 — Hot-reload сервис подключён под env-флагом HOT_RELOAD (default OFF) · High
- **Файл:** `src/services/config_watcher.py`, `src/main.py` (`run_platform`)
- **Проблема:** `ConfigWatcher` был реализован, но нигде не инстанцируется. Также `tests/test_hot_reload.py`, на который ссылается roadmap Phase 6, **не существует** (есть только `test_hot_reload_memory.py` — тесты unregister/памяти FSM)
- **Статус:** ✅ **Подключено** (2026-09-30, Q3 из BACKLOG) — watcher создаётся/стартует в `run_platform()` под `HOT_RELOAD=1` (проверка `hot_reload_enabled()`, default OFF — риски ниже), остановка в `finally`; явная сборка `Container` в main (PlatformContext контейнера не содержит); починены: `stop()` без start/повторный, `_is_manifest_file` (абс/отн пути), удалён мёртвый аргумент `loader` (несуществующий тип); тесты `tests/test_config_watcher.py` (20 passed: lifecycle, детекция, реальный reload через watchdog, env-флаг); smoke: `HOT_RELOAD=1` → started/stopped в логах
- **Риски ДО включения по умолчанию:** (1) колбэки reload выполняются в потоке watchdog — гонки с event loop (`register_definition` зовёт `asyncio.get_event_loop()`); (2) reload сбрасывает состояние FSM в `initial_state` (`restore_state=False`); (3) EventRouter-маппинг и кэш `Container._manifest` не обновляются; (4) отсутствует enable/disable в конфиге манифеста (только env)
- **Остаток:** `tests/test_hot_reload.py` из roadmap не создан (есть покрытие в `test_config_watcher.py`)


### #9 — Канал доставки `params.motion_sensor` мёртв · Low
- **Файлы:** `src/adapters/ha_adapter.py:300`, `src/core/fsm/factory.py:399`
- **Проблема (как записано 2026-09-29):** `HAAdapter` публикует `state_change` на `engine.event_bus`, но у `FSMEngine` такого атрибута нет → ветка уходит в `engine.trigger()` по несуществующему entity → подписка `_subscribe_to_sensor_events` никогда не срабатывает, даже если `motion_sensor` указан в params. Штатная доставка идёт через EventRouter (room sensors) — после фикса #1 работает
- **Уточнение 2026-10-07 (проверкой кода и запуском, а не чтением заметки):** мёртвым был не канал `motion_sensor`, а **вся** доставка событий Home Assistant. У настоящего `FSMEngine` шина названа `_event_bus`, публичного `event_bus` нет, поэтому `hasattr` давал `False` и работала **только** запасная ветка. Последствия шире записанного: `DeviceService.handle_state_change` в бою не вызывался ни разу (состояние меняла только ручная синхронизация), `broadcast_state_change()` не получал данных для клиентов, `FSMStateBridge` не писал события устройств в журнал (графики активности читают именно эту таблицу), каждое изменение состояния давало отказ `unknown_entity`. Тесты этого не видели: движок в них — `MagicMock`, атрибут появляется сам, а единственный тест запасной ветки подменял `builtins.hasattr`, чтобы её достичь
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-10-07) — публичное свойство `event_bus` у `FSMEngine`; адаптер публикует на шину без `hasattr`, запасная ветка с `engine.trigger()` удалена (она и была причиной отказов). Проверки: `tests/test_state_change_delivery.py`, 13 штук на настоящих движке, шине и сервисе устройств; инъекция прежнего кода роняет 9. Переписан `test_on_state_change_fallback_to_direct_trigger` — он закреплял поведение, которого в бою не было. Не проверено в доме


### #10 — MockAdapter не маршрутизирует state change события · Low
 - **Файл:** `src/adapters/mock_adapter.py:158-165`
 - **Проблема:** `set_event_router()` сохраняет роутер в `_event_router`, поле больше нигде не используется → в mock-режиме (без HA_TOKEN) motion-события не доставляются FSM
 - **Статус:** Не исправлено (влияет только на демо/mock-сценарии)


### #11 — US4 Access Control не подключён — права фактически не проверяются · High
*(найдено 2026-09-29 при сверке specs/001)*
- **Файлы:** `src/webui/middleware_access_control.py` (не подключён), `src/webui/routes/devices/devices.py:79-82` (фильтрация закомментирована), `src/webui/routes/devices/websocket.py:158-174` (проверка закомментирована), `src/webui/routes/devices/access_control.py:104-206` (grant/revoke/list — заглушки)
- **Проблема:** `DeviceAccessMiddleware` создан, но нигде не зарегистрирован; проверки доступа на device-endpoints отключены; эндпоинты выдачи прав возвращают заглушки (`UUID(int=0)`, `[]`)
- **Бэклог:** Technical Debt → High Priority в `03_ROADMAP.md`, `specs/001-device-integration/tasks.md` → «Бэклог»
- **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-29) — specs/004-device-access-control: middleware зарегистрирован в `create_app` (+`access_control.router` не был включён вовсе — 404), фильтрация `GET /api/v1/devices` по `get_user_accessible_devices`, grant/revoke/list на body-схемах с реальной логикой (grant device-blind), WS-подписка с `check_device_access` + доставка по правам при каждой доставке; module-level `app` в `src/main.py`; contract access 11 passed, integration access 2 passed. Отклонение: `grant_access` не требует существования устройства (grant до синка)


### #12 — `Task was destroyed but it is pending` при остановке контейнера · Low
*(найдено 2026-09-29 при T011)*
 - **Файл:** контейнер `behavioral-platform`, uvicorn `Server.shutdown()` (Task-169)
 - **Проблема:** при `docker compose stop` event loop закрывается с pending-задачей self-shutdown uvicorn; критерии T011 (`Traceback`/`Unclosed client session`, останов ≤30с) при этом выполняются (останов 1с, 0 ошибок)
 - **Статус:** Не исправлено (низкий приоритет, косметика graceful shutdown)


### #13 — `tests/test_webui_playwright.py` заражает event loop'ом весь root-прогон · High
 - **Файл:** `tests/test_webui_playwright.py` (async-тесты с playwright `page`)
 - **Проблема:** session-фикстура playwright sync API (`playwright/sync_api/_context_manager.py:55` — `loop.run_until_complete(run_as_sync())` внутри greenlet) держит event loop в состоянии **running на протяжении всей pytest-сессии** после первой playwright-фикстуры → все последующие async-тесты падают с `RuntimeError: Runner.run() cannot be called from a running event loop`; даже синхронный тест с `asyncio.run()` после него падает. В root-прогоне под удар попадали: все 14 playwright-тестов (они были `async def` — конфликт sync API), ~51 `test_device_service.py`, 9 `test_device_sync_persistence.py` (specs/005) и др.
 - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q1 из BACKLOG) — (1) 14 тестов переведены на **sync API** (`def` без `await` — pytest-playwright предоставляет sync `page`), (2) файл исключён из общего прогона: `--ignore=tests/test_webui_playwright.py` в `[tool.pytest.ini_options] addopts` (`pyproject.toml`), запуск отдельно: `pytest tests/test_webui_playwright.py` (документировано в шапке файла). Проверено: root-прогон **15 failed / 1301 passed = baseline** (было 87), `run_checks.sh` exit 0
 - **Остаток (Q6):** ✅ закрыт 2026-09-30 — отдельный прогон playwright починен (см. ниже); **осталась мелочь:** та же битая ASGI-цель `src.webui.app:app` в автофикстуре `tests/conftest.py::webui_server` — сервер не поднимается, фикстура тратит ~15с ожидания и поднимает мёртвый процесс на каждый прогон (тесты её не используют; кандидат на удаление → BACKLOG §3)


### #14 — `MockAdapter` без `start()`/`stop()` — `run_platform` падает в mock-режиме · High
*(найдено 2026-09-30 при smoke Q3)*
 - **Файл:** `src/adapters/mock_adapter.py` (нет `start`/`stop`), вызов `await ctx.adapter.start()` в `src/main.py`
 - **Проблема:** при запуске без `HA_TOKEN` (MockAdapter) `run_platform` падает с `AttributeError: 'MockAdapter' object has no attribute 'start'` ещё до старта uvicorn — штатный локальный запуск `PYTHONPATH=. python -m src.main` в mock-режиме не работает (в Docker/HA-режиме `HAAdapter.start` есть)
 - **Статус:** ✅ **ИСПРАВЛЕНО** (2026-09-30, Q7 из BACKLOG) — `MockAdapter.start()/stop()` (async no-op, идемпотентные, флаг `_started`, лог старт/стоп); `tests/test_mock_adapter.py` (8 тестов: lifecycle, идемпотентность, restart, `PlatformContext.start/shutdown` ×2 без `HA_TOKEN`); smoke: `PYTHONPATH=src python -m src.main` без `HA_TOKEN` → `/health` = `{"status":"ok"}`, 0 Traceback; полный прогон 29 failed (baseline) / 1382 passed (+8)


### #15 — Два Playwright-теста `TestDeviceManagement` падают при отдельном прогоне · High
~~ ✅ **ИСПРАВЛЕНО 2026-10-03** *(найдено 2026-10-01, T049)*
- **Файлы:** `tests/test_webui_playwright.py` (`test_change_device_room`, `test_add_device_to_room`)
- **Исходная формулировка была неточной:** модалка не закрывалась не из-за порядка прогона и не из-за `htmx:afterRequest`. Форма **вообще не отправлялась**: поле `source_id` обязательно (`required`), а источников в чистом E2E-окружении нет, поэтому `form.checkValidity()` возвращал `false`, браузер блокировал отправку, htmx-запроса не было — и `hx-on::after-request` со `bootstrap.Modal.hide()` не срабатывал. Найдено пробой браузера: 0 запросов после клика, `valid: false`
- **Причина в требованиях:** источник в форме обязателен намеренно (F1, specs/006 — без источника устройство не с чем синхронизировать). Тесты сохраняли устройство, не выбрав источник
- **Исправление:** `_ensure_ha_source_exists()` создаёт источник через API от имени администратора, `_select_source(page)` выбирает его в форме. Источник создаётся **в двух конкретных тестах**, а не в сессионной фикстуре: вариант с общей фикстурой менял состояние всего файла и приводил к таймауту pytest и суммарно >900 с
- **Проверено:** `pytest tests/test_webui_playwright.py` — **25 passed / 0 failed за 36.69 с**, таймаутов pytest-timeout нет (было 23 passed / 2 failed за 149 с). Часть ускорения — следствие удаления автофикстуры `webui_server` (B10), которая напрасно ждала порт 15 с на каждой сессии
- **Оговорка:** это один чистый прогон; причина была детерминированной (валидация формы), поэтому воспроизводимость не вызывает сомнений, но при прогоне в CI стоит убедиться ещё раз


### #16 — Генератор диаграмм объединяет несколько машин устройства в одну схему · Low
— при нескольких поведениях схема получается плотной; каждый автомат имеет собственные состояния, поэтому при желании их можно рисовать отдельными схемами
- **Файл:** `src/webui/routes/__init__.py::_build_mermaid_state_diagram`
- **Статус:** Не исправлено (текущий вид читаем: подписи рёбер усекаются до 2 триггеров, дубликаты рёбер объединяются)


### #17 — Реестр гвардов и действий движка не используется в производстве · Low
*(выявлено 2026-10-01, R-11)*
- **Файл:** `src/core/fsm/engine.py` (`_guards`, `_actions`, `register_guard`, `register_action`)
- **Проблема:** фабрика разрешает имена гвардов и действий через отдельный `Registry` и подставляет готовые callable прямо в `Transition`, поэтому `_guards`/`_actions` движка остаются пустыми. Методы используются только в тестах и демо
- **Статус:** Не исправлено (мёртвый код вне пути данных фичи; удаление требует отдельной задачи, чтобы не сломать `tests/test_fsm.py`)


### #18 — Ручная блокировка не включалась ни одним путём · Critical
*(выявлено 2026-10-01 как R-03/R-11; масштаб уточнён 2026-10-07 проверкой кода)*
- **Файлы:** `src/adapters/ha_adapter.py` (разбор конверта события), `src/core/commands/middleware.py` (список ручных источников), `src/webui/routes/devices/devices.py` (источник команды из веб-интерфейса)
- **Как было записано:** «движок не подставляет `source` и `priority` в контекст действия, поэтому набор ручных источников в middleware недостижим»
- **Уточнение 2026-10-07: запись описывала следствие, а не причину.** Метод `_is_manual_source` был достижим; недостижимы были **данные**. Два независимых обрыва: (1) Home Assistant кладёт указание пользователя в конверт события, а разбор отдавал обработчику только `data` — указание подставлялось заглушкой; (2) команда из веб-интерфейса помечена источником `manual_command`, которого не было в списке
- **Настоящее последствие шире записанного:** блокировка не включалась **никогда**, то есть человек выключал свет, а автоматика включала его обратно. Для дома это хуже любой неработающей функции: систему отключают на второй день
- **Статус:** ✅ **ИСПРАВЛЕНО 2026-10-07** (спека 010, US1) — конверт разбирается целиком, `manual_command` внесён в список ручных источников и вынесен в константу, дополняется из манифеста. Проверок 14, откат каждой правки роняет свои (1 и 6). Не проверено в доме


### #19 — `ContextManager` подписан на непубликуемое событие · Low
*(выявлено 2026-10-01, R-11; пересмотрено 2026-10-07)*
- **Файл:** `src/core/persistence/context_manager.py` (`ha.state_changed`)
- **Проблема:** событие `ha.state_changed` не публикуется никем, поэтому контекст по датчикам и расписаниям не наполняется
- **Пересмотрено 2026-10-07: запись снимается как основание для работы.** (1) Состояния автоматов переживают перезапуск — запись утверждала обратное по состоянию на 2026-10-01, с тех пор это исправлено (#78, `state.json` с временем входа). (2) Графики активности и истории наполняются другим путём: мост состояний пишет `SensorEvent` по событию доставки, а после починки #9 эта доставка заработала впервые. (3) Условия по датчикам получают значение из контекста перехода, а не из этого хранилища — это сделано в спецификации 010 (US2)
- **Статус:** Не исправлено (требует публикации событий Home Assistant — отдельная задача), но как основание для приоритета снято


### #20 — Префикс-коллизия при горячей перезагрузке манифеста · Low
*(выявлено 2026-10-01, R-11)*
- **Файл:** `src/services/config_watcher.py:329-331`, `:400`
- **Проблема:** принадлежность FSM проверяется через `fsm_id.startswith(device_id)` без подчёркивания, поэтому устройство `light.a` забирает автоматы устройства `light.ab_*`
- **Статус:** Не исправлено (не связано с состояниями автоматов; отдельная задача)


### #21 — `/metrics` открыт без аутентификации, как `/health` · Low
— перечень открытых диагностических точек зафиксирован в `specs/008-fsm-observability/contracts/metrics-api.md` §1.6
 - **Почему так:** мониторинг опрашивает показатели без пользователя; аутентификация на диагностической точке потребовала бы новых учётных данных и нового кода вне объёма фичи. Тело содержит имена устройств, уже видимых владельцу в своей сети
 - **Статус:** Не исправлено (введение аутентификации диагностики — отдельная задача)


### #22 — Правило «Services не импортирует Core» в конституции не соответствует коду · Low
— `services/fsm_state_bridge.py`, `services/device_service.py` и новый `services/metrics_reporter.py` импортируют `core.*`
 - **Почему не здесь:** связывающее правило — ADR-001 «Core не зависит от Adapters» — соблюдается; новый сервис следует образцу существующего кода, а не вводит вторую схему. Отклонение зафиксировано в `specs/008-fsm-observability/plan.md` → Complexity Tracking
 - **Статус:** Не исправлено (правка конституции — вне объёма фичи)


### #23 — `src/dashboard/lovelace_generator.py` недостижим из production-кода · Low
— помечен мёртвым в докстринге
 - **Почему не здесь:** решение D-3 называло модуль `DashboardIntegration`, а не генератор; удаление не санкционировано. FR-025 закрыта явной пометкой
 - **Статус:** Не исправлено (кандидат на удаление в отдельной задаче)


### #24 — Состояния без таймингованных переходов зависанием не считаются по построению · Low
— сторож знает, что ждать нечего
 - **Почему так:** ручной порог ожидания стал бы вторым источником правды, способным разойтись с описанием автомата, и давал бы ложные срабатывания на состояниях, живущих по часам и суткам
 - **Статус:** По конструкции (проверено тестами и вживую: `expected_timeout_sec=None` → `stuck=false`)


### #25 — Показатели не хранятся исторически · Low
— `/metrics` отдаёт срез на момент запроса
 - **Почему так:** историческое хранение — отдельная система, прямо исключена из объёма фичи спецификацией
 - **Статус:** По конструкции (перезапуск процесса обнуляет счётчики — FR-010, задокументировано в контракте)


### #26 — `split_fsm_id` не разбирает имя устройства, если шаблон содержит подчёркивание · Low
— для `fan.bathroom_humidity_ventilation_5` даёт устройство `fan.bathroom_humidity`, поведение `ventilation`
 - **Почему не здесь:** ADR-003 утверждает, что имя устройства подчёркиваний не содержит; имя шаблона может. Наблюдаемое в F3 устройство в снимках сторожа берётся из описания (`FSMEngine.device_id_of`), поэтому на приёменку фичи не влияет, но на выгрузке событий (`build_transition_payload.behavior`) сказывается
 - **Статус:** Не исправлено (отдельная задача на правило разбора идентификатора)


### #27 — Файл `tests/test_webui_fsm_e2e.py` не содержит ни одного исполняемого теста · Low
*(выявлено 2026-10-03, сверка с кодом)*
 - **Файл:** `tests/test_webui_fsm_e2e.py`
 - **Проблема:** три закомментированных теста, селекторы устарели, собственная фикстура пишет в каталог данных репозитория. Файл при этом указывался в `01_PROJECT_STATE.md` как покрытие Web UI — то есть выглядел как проверка, ничего не проверяя
 - **Статус:** Исправляется в specs/009 (T012) — покрытие этих сценариев строго сильнее даёт `tests/test_webui_playwright.py` (25 работающих тестов)


### #28 — Прогоны тестов пишут в `data/` репозитория · Low
*(выявлено 2026-10-03, измерением)*
 - **Файлы:** `tests/contract/test_sources_api.py`, `tests/contract/test_devices_api.py`, `tests/contract/test_access_control.py`, `tests/contract/test_fsm_live_contract.py`, `tests/integration/test_device_audit_log.py` и др. — все, что берут синглтон `from src.main import app`
 - **Проблема:** `create_app` собирает `PersistenceManager(data_dir="data")` — относительный путь, разрешаемый от текущего каталога (`src/webui/app.py:367`). Каждый полный прогон добавляет **31 источник** (+17 123 байта) и пишет записи доступа, которые **навсегда остаются** в каталоге. Каталог в `.gitignore`, поэтому рост не виден в `git status`; накоплено 2611+ источников — следы прогонов, а не данные установки
 - **Почему не здесь:** изолирующие фикстуры в specs/009 построены и работают (вклад 0 байт, проверено контрольным прогоном), но перевод всех существующих тестов на них — отдельная работа, не входящая в буквальный объём фичи
 - **Статус:** ✅ Исправлено в specs/009 (`a7fe338`): причина оказалась в том, что хранилища создаются на уровне модуля (`event_store = EventStore()` в `src/webui/routes/__init__.py:36`), поэтому каталог создавался уже при импорте. `DATA_PATH` выставляется в `tests/conftest.py` на этапе импорта; шесть файлов тестов переведены с `os.chdir` на явный `DATA_PATH`


### #29 — 40 тестов не проверяют результат · Low
*(выявлено 2026-10-03, AST-скан по всему `tests/`)*
 - **Файлы:** 26 файлов; массово — `tests/test_metrics.py:304-334`, `tests/unit/test_fsm_state_bridge.py`, `tests/unit/webui/test_websocket_connection_manager.py`, `tests/unit/test_device_service.py`, `tests/test_event_bus.py`
 - **Проблема, класс A (35 тестов):** проверяют лишь отсутствие исключения — проходят, если код ничего не сделал. Названия вроде `test_should_not_raise_when_dispatcher_fails` описывают корректное намерение, но не дают гарантии, что ветвь отказа вообще была достигнута
 - **Проблема, класс B (5 тестов):** комментарии прямо признают отсутствие проверки. Хуже всего `tests/test_ha_adapter.py:443 test_connect_websocket_exponential_backoff` — объявляет `failing_connect()`, **но ни разу её не вызывает**, заканчивается `pass`. Экспоненциальный откат не проверяется вообще. Также: `tests/test_webui_specification.py:226` (имя обещает перенос устройства между комнатами, тело результата не проверяет), `tests/test_context_manager.py:353`, `tests/test_state_store.py:215,371` (docstring обещает проверку дебаунса, тело только вызывает `save()`)
 - **Ошибка в исходной оценке числа.** Заявленные «40» отражали два дефекта сканера, а не 40 тестов: (а) `"expect(" in ast.dump(node)` **никогда не срабатывает** — дамп рендерит вызов как `Call(func=Name(id='expect'))`, без скобки, поэтому 13 браузерных тестов попадали в список, а я считал их нормальными; (б) `tests/test_lovelace_generator.py::test_manifest_with_behaviors` помечена `@pytest.fixture`, и pytest 8.4.2 помечает объект фикстуры `__test__ = False`, то есть она не собирается вовсе. Точный скан с подсчётом узлов `ast.Assert` даёт **39** реальных тестов, из них 33 класса A и 6 класса B. Критерий «`Assert` в дампе» к тому же давал ложные срабатывания на `raise AssertionError(...)`
 - **Исправлено в specs/009 (T030), все 39.** Класс B: `test_connect_websocket_exponential_backoff` — проверяет полную последовательность пауз 1, 2, 4, 8, 16, 32, 60 секунд (попыток намеренно семь: при шести последняя пауза равна 32, ветка насыщения `min(..., 60.0)` недостижима, и проверка потолка пуста — тест прошёл бы при потолке 10 секунд); остальные 5 переписаны на фактические проверки. Класс A: каждому добавлено утверждение о **наблюдаемом состоянии**, а не «не бросило». Там, где правильный код и пустое тело неразличимы (отмена несуществующего таймера, `stop` до `start`, отключение неизвестного соединения), тест получил **контрольную половину** — вызов на существующем объекте, без которого проверка «ничего не изменилось» была бы пустой. Чувствительность доказана **79 мутациями** production-кода; все откачены побайтово
 - **Побочные находки** (дефекты production-кода) вынесены в #39; долг mypy — туда же
 - **Статус:** ✅ Исправлено в specs/009


### #30 — 10 тестов в файле, который pytest не собирает · Low
*(выявлено 2026-10-03, спека 009)*
 - **Файл:** `tests/security/verify_security.py`
 - **Проблема:** имя файла не матчит `python_files = test_*.py`, поэтому `pytest tests/` его пропускает. Внутри — 4 теста шифрования (перенесены в `tests/unit/core/test_encryption.py`, T010) и **6 рабочих тестов анализатора безопасности логов** (`test_no_plaintext_tokens_secure`, `test_no_plaintext_tokens_insecure`, `test_sensitive_fields_masked`, `test_error_messages_safe`, `test_exception_safety`, `test_report_generation`), которые выполняются, но не видны ни в одной проверке. Первоначальная формулировка спеки («4 теста») недооценила проблему вдвое
 - **Статус:** Частично исправлено в specs/009 (шифрование перенесено, T010/T011); перенос 6 тестов анализатора — задача T011a


### #31 — `check_sensitive_fields_masked` пропускает незамаскированный токен · Low
*(выявлено 2026-10-03, спека 009 T011a)*
 - **Файл:** `tests/security/verify_security.py:31-40` (`SENSITIVE_PATTERNS`)
 - **Проблема:** список содержит `password`, `secret`, `api_key`, `apikey`, `auth`, `credential`, `access_token`, `refresh_token` — **голого `token` нет**, а подстрока `"auth"` в `"token"` не встречается. Поэтому поле `{"token": "<JWT>"}` считается нечувствительным и проходит проверку
 - **Расхождение заметно:** `check_no_plaintext_tokens` тот же токен ловит (срабатывают и JWT-паттерн, и `token[:=]`), а пример безопасных логов в самом анализаторе использует `token="***REDACTED***"` — то есть поле задумано чувствительным
 - **Почему не здесь:** правка меняет поведение проверки безопасности логов, а FR-026 фичи 009 требует фиксировать такие дефекты отдельной задачей, а не править молча. Пробел зафиксирован тестом с **фактическим** поведением (`test_bare_token_field_is_not_checked_by_masking_check`), поэтому он виден, а не замаскирован
 - **Статус:** Не исправлено (после исправления тест нужно перевернуть на `assert not is_valid`)


### #32 — Команда `export-fsm` не работала никогда · Low
*(выявлено 2026-10-03 при написании тестов, спека 009 US2)*
 - **Файлы:** `src/smart_home/cli/commands/export_fsm.py:58` (исполняемый импорт), `:22` и `src/services/config_watcher.py:42` (под `TYPE_CHECKING`)
 - **Проблема:** `from core.fsm import FSMEngine` при **пустом** `src/core/fsm/__init__.py` → `ImportError` при любом штатном запуске команды, до всякого вывода, код возврата 1. Остальной код использует верный путь `core.fsm.engine` в шести местах
 - **Почему не ловилось:** mypy настроен на пакет `src.smart_home` и пакет `core` не резолвит, поэтому неверный импорт проходил молча. Ни одного теста у команды не было — поломка не всплыла
 - **Почему исправлено в этой фиче, а не вынесено:** обычный дефект production-кода фиксируется отдельной задачей (FR-026), но здесь дефект делал невозможным закрыть US2 — команда неработоспособна, значит её тесты не могут стать зелёными ни при каком виде тестов. Правка минимальна: только путь импорта, поведение не менялось. Проверено запуском: был exit 1 с трассировкой, стал exit 0 с корректным `stateDiagram-v2`
 - **Статус:** ✅ Исправлено в specs/009 (`13a8c68`)


### #33 — Пустой `src/core/fsm/__init__.py` допускает повторение таких импортов · Low
*(выявлено 2026-10-03)*
 - **Файл:** `src/core/fsm/__init__.py` (0 строк)
 - **Проблема:** пакет не реэкспортирует публичные имена, хотя `src/core/__init__.py:11` это делает. Любой новый `from core.fsm import ...` снова сломается — и снова молча пройдёт mypy
 - **Статус:** Не исправлено (реэкспорт либо линтер-правило — отдельная задача; проверка надёжнее перечисления: AST-обход всех импортов `core.*` в `src/` показал 0 проблем)


### #34 — Контрактные тесты прав проверяли несуществующие устройства · Low
*(выявлено 2026-10-03, спека 009 T028)*
 - **Файл:** `tests/contract/test_access_control.py`
 - **Проблема:** фикстура `sample_device` возвращала словарь со **случайным `uuid4()`**, который никогда не создавался в системе. Каждый тест класса `TestAccessControlAPI` обращался к несуществующему устройству и получал `404`, а ассерты допускали `[200, 404]` / `[403, 404]` — то есть проходили независимо от того, работает ли разграничение прав. Восемь тестов выглядели как контракт прав, но не проверяли прав: отказ по правам и отсутствие устройства давали один и тот же наблюдаемый результат
 - **Почему не видно было:** все тесты зелёные; расхождение обнаружено только чтением кода при написании `tests/contract/test_device_access_rights.py`
 - **Что сделано:** фикстура создаёт настоящее устройство через `seed_device_in_service`; все допуски заменены конкретными ожиданиями (`403` для отказа по правам, `202` для команды, `204` для отзыва, `200` со списком); отзыв проверяется по **выданной** записи, а не по случайному идентификатору. Заведён запрет на возврат таких допусков: `tests/contract/test_no_intolerant_status_assertions.py`
 - **Статус:** ✅ Исправлено в specs/009


### #35 — Ещё 3 места с неразличимым допуском, вне области прав · Low
*(выявлено 2026-10-03, спека 009 T028)*
 - **Файлы:** `tests/contract/test_devices_api.py:80,324,337`, `tests/test_webui.py:161`, `tests/test_webui_specification.py:679`
 - **Проблема:** `assert response.status_code in [200, 404]` в тестах HTTP-интерфейса и команды. Вне проверок прав такой допуск терпим — устройство заведомо может отсутствовать, — но и здесь он ослабляет проверку: тест не отличает «сработало» от «объекта нет»
 - **Почему не здесь:** перевод требует по каждому месту решить, какое поведение считать правильным, то есть понимания, что проверяет тест. Это отдельная работа по 3 местам, а не механическая правка
 - **Статус:** Не исправлено (`tests/contract/test_no_intolerant_status_assertions.py` намеренно проверяет только файлы проверки прав — расширение области требует решения по каждому месту)


### #36 — Обработчики ответов накапливаются при таймауте · Low
*(выявлено 2026-10-03, спека 009 T030)*
 - **Файл:** `src/adapters/ha_adapter.py:144-172` (`SimpleHAWebSocketClient.get_states`), аналогично `call_service(return_response=True)`
 - **Проблема:** обработчик ответа регистрируется в `self._handlers[msg_id]` и снимается только при получении ответа. По истечении `asyncio.wait_for(..., timeout=15)` обработчик **остаётся** в словаре. При молчащем Home Assistant `_handlers` растёт бесконечно; в цикле переподключения это утечка памяти
 - **Почему не видно было:** два теста мокали `ws.recv`, который `get_states()` **никогда не вызывает** — результат приходит через фоновую задачу `_listen_loop`. Оба теста упирались в полный 15-секундный таймаут и возвращали `[]`, а `assert isinstance(states, list)` проходил для пустого списка. Тест назывался «returns_result», но результата не проверял
 - **Почему не исправлено:** FR-026 требует фиксировать дефекты production-кода отдельной задачей. Правка поведения (`pop` обработчика в `finally`) затрагивает конкурентный доступ к `_handlers` и требует отдельного решения, а не механической правки в фиче о тестах
 - **Уточнение 2026-10-07: масштаб завышен, утечки в работающей системе нет.** Словарь `_handlers` очищается при каждом подключении (`ha_adapter.py:100`), то есть в цикле переподключения утечка не накапливается. Ожидание ответа не включается ни одним вызовом в production: диспетчер и сервис устройств зовут `call_service` без `return_response`, а `get_states` вызывается только при ручном сканировании мастером discovery. Остаётся косметика: один оставшийся обработчик на неудавшийся вызов `get_states`
 - **Статус:** Не исправлено · понижено с «утечки памяти» до косметики


### #37 — Два теста тратили 30 секунд и не проверяли результат · Low
*(выявлено 2026-10-03, спека 009 T030)*
 - **Файлы:** `tests/test_ha_adapter.py::TestSimpleHAWebSocketClient::{test_ws_client_get_states_timeout, test_ws_client_get_states_returns_result}`
 - **Проблема:** оба мокали `ws.recv`, который `get_states()` не вызывает, поэтому всегда выжидали полный таймаут 15 с и возвращали `[]`. Второй подставлял JSON с `"result": [...]`, который никто не читал, а проверка `isinstance(states, list)` была тривиально верна для `[]`
 - **Что сделано:** переписаны через настоящий протокол — подставной сокет отвечает как Home Assistant, запускается реальная `_listen_loop`, проверяется точное содержимое ответа, снятие обработчика из `_handlers` и то, что `recv()` не вызывается вовсе. Таймаут проверяется перехватом `asyncio.wait_for` с оригинальным вызовом при `timeout=0.01` — путь отмены future подлинный. Добавлен третий тест, фиксирующий фактический контракт, чтобы старый вакуумный мок не вернулся
 - **Эффект:** файл 30.76 с → **0.67 с**; чувствительность обоих тестов подтверждена мутациями production-кода
 - **Статус:** ✅ Исправлено в specs/009


### #38 — 23 пропускных механизма внутри тестов · Low
*(выявлено 2026-10-03, спека 009 T030; снято 2026-10-04)*
 - **Состояние:** ✅ **ИСПРАВЛЕНО.** Снято **23** пропускных механизма: 21 условный самопропуск в теле теста + 2 `pytest.importorskip`. Приёмка: `grep -rn "pytest\.skip\|importorskip\|skipif\|xfail" tests/` не находит ни одного механизма вне комментариев и докстрингов; прогон `pytest tests/ -q` — **1996 passed, 0 skipped, 0 failed**
 - **Файлы (23):** `tests/contract/test_access_control.py` (11), `tests/contract/test_devices_api.py` (9), `tests/test_manifest_validator.py` (1), `tests/test_secrets.py` (2 `importorskip`). Сопутствующее исправление в том же проходе, не являющееся пропуском: `tests/test_scene_manager.py` — заморозка часов вместо чтения системного времени
 - **Почему молчание опасно — guards были недостижимым кодом.** Прежняя форма: `if not sample_device: pytest.skip("Sample device creation failed")`. `skipped == 0` достигался **именно тем, что guard не срабатывал**: инвариант выполнялся и одновременно ничего не гарантировал. Метрика «пропусков нет» была достигнута условием, которое её и отменяет. Стоило подготовке однажды сорваться — и вместо падения получался `skipped`, то есть **деградация проверки выглядела как успех**. Хуже всего цепочка была трёхзвенной: фикстура `sample_source` возвращала `None` при коде ответа не `201` → фикстура `sample_device` возвращала `None` → тест пропускался. Отказ подготовки превращал 20 тестов в no-op, и ни один сигнал этого не показывал
 - **Что сделано — guards перенесены из тестов в фикстуры, где стали требованием.** Абстрактный пропуск заменён предварительным условием: фикстура `sample_source` в обоих контрактных файлах теперь `assert response.status_code == 201` с телом ответа сервера в сообщении, плюс проверка наличия `id` и **обратное чтение созданного** через API (`GET /sources/{id}` → 200 с тем же `id`). Обратное чтение существенно: «201» сам по себе не доказывает, что источник создан, поэтому подстановка выдуманного `id` больше не проходит незамеченной. Фикстуры `sample_device` проверяют `source_id` и **читают посеянное устройство обратно** (`GET /devices/{id}` → 200) — иначе тесты ниже проверяли бы контракт 404 вместо контракта устройства
 - **`test_manifest_validator.py`: ветка была недостижима принципиально.** Guard стоял на `Path("instances/leonids_house/manifest.yaml").exists()`. Это репозиторный артефакт, отслеживаемый git (проверено `git ls-files`), а не необязательная внешняя зависимость, поэтому «файла нет» означает повреждённое состояние репозитория, а не «проверка неприменима». Путь перестроен от корня репозитория (каталога с `tests/`), а не от текущего рабочего каталога, — иначе «файла нет» означало бы просто неудачный `cd`. Теперь отсутствие файла падает с внятным сообщением
 - **`test_secrets.py`: `pytest.importorskip` на dev-зависимость превращал ошибку настройки окружения в тихий пропуск.** `python-dotenv` объявлен в `[project.optional-dependencies].dev`, то есть в тестовом окружении присутствует по определению; его отсутствие — не «причина не применять», а сломанное окружение. На месте `importorskip` заведена фикстура `require_dotenv`, которая **требует** импорта и падает, если его нет
 - **Попутно вскрыто при снятии пропусков.** Пропуски маскировали две настоящие проблемы, которые пришлось устранить, чтобы guards стали достижимыми: (1) в `test_devices_api.py::test_get_device_by_id_success` фикстура источника бралась, но не использовалась — тест подставлял случайный `uuid4()` и допускал `status_code in [200, 404]`, то есть ассерт не мог упасть (для случайного id сервер всегда отвечал 404); тест числился проверкой контракта `GET /devices/{id}` и не проверял ничего. Теперь устройство создаётся каноническим `POST /devices/apply`, а ответ сверяется точно, включая требование `data == created` — оба ответа строятся одним `_to_device_response`, и расхождение означало бы разные контракты (это Known Issue #35). (2) `test_scene_manager.py::test_check_time_triggers` читал `datetime.now()` в тесте, тогда как production-код читал его отдельно, — на границе минуты тест становился флакующим. Заморожено именно то время, которое читает `src.core.scene_manager`: подмена `datetime` в самом тесте не действовала бы, тест и код читали бы два разных источника
 - **Почему guards нельзя было считать безобидными.** Пока они не срабатывали, это был мёртвый код; но их снятие немедленно превратило деградацию подготовки в падение. Поэтому снятие сопровождалось не только удалением `pytest.skip`, но и доведением подготовки до состояния, в котором она не может сорваться молча


### #39 — Девять дефектов, вскрытых переписыванием пустых тестов · Low
*(выявлено 2026-10-03, спека 009 T030)*
 - **`FileStateStore.debounce_sec` — мёртвый параметр.** `src/core/persistence/state_store.py:169` — значение сохраняется и **не читается ни в одном методе** (проверено `grep`). Дебаунса нет: `save()` пишет только в `_cache` и `_pending_writes`, файл появляется исключительно из `flush()`/`clear()`. Тест `test_debounce` обещал проверку дебаунса, которого не существует
 - **`DebouncedStateStore` не соблюдает интервал до первой записи.** Условие `now - self._last_write_time >= self._debounce_sec` при `_last_write_time = 0.0` истинно всегда, поэтому первая фоновая запись происходит немедленно, минуя интервал
 - **Фоновую задачу дебаунса нечем остановить.** `_schedule_flush` не перезапускает живую задачу, а цикл `_background_flush` бесконечный — отменять такие задачи нечем, они живут до конца цикла событий
 - **Перенос устройства между комнатами дублирует устройство.** `lifecycle_service.add_device(..., room_id="living_room")` не удаляет устройство из старой комнаты: подтверждено по HTML, по сохранённому YAML и по `lifecycle_service.manifest` — `kitchen` и `living_room` содержат одно и то же устройство. Имя теста `test_device_removed_from_old_room_after_move` обещало обратное; зафиксировано фактическое поведение
 - **`websocket_batcher._flush_batch`: исключение из асинхронного callback не ловится.** Для async-callback выполняется `asyncio.create_task(...)`, тело корутины уходит за пределы `try`, поэтому исключение всплывает как «Task exception was never retrieved» и **не попадает в журнал батчера**. `except` срабатывает только для синхронного callback, то есть `logger.error(..., exc_info=True)` в основном сценарии недостижим
 - **`src/services/device_service.py` использует stdlib `logging` вместо loguru**, хотя `.ai/04_RULES.md` предписывает loguru, а `EventBus` его использует. Побочный эффект: перехват логов через loguru-sink молча ничего не видит — на это наступили при написании тестов
 - **`old_state` из Home Assistant игнорируется.** `src/services/device_service.py:1135` — `event_data.get("data", {}).get("old_state")` вычисляется, но результат не используется; в публикуемое событие `old_state` попадает из `device.state.copy()`
 - **Один `try` на весь цикл расчёта доступности.** `DeviceService._update_device_availability_metrics` — сбой `set_devices_available` прерывает цикл, и `set_devices_unavailable` для этой и всех следующих групп молча пропускается, то есть gauge «недоступные» устаревает
 - **`WatchdogService.start()` помечает себя запущенным до создания задачи.** Флаг `_running = True` выставляется **до** `asyncio.create_task(...)`; если создание задачи падает, сторож навсегда остаётся помеченным запущенным и `start()` больше не сработает
 - **Долг mypy:** 6 ошибок в `tests/cli/test_bulk_import.py:254` (`func-returns-value`) и `tests/integration/test_discovery_routes.py:156,168,366,380` (`dict-item`). Предсуществующие, не регрессия
 - **Непокрытым остался `PluginLoader.unload_all` при непустом реестре** — цикл `disconnect()` / `instance = None` / `is_loaded = False` не проверяется ни одним тестом репозитории
 - **Расхождение путей импорта:** `tests/test_event_bus*.py` импортирует `core.events.event_bus`, `tests/unit/*` — `src.core.events.event_bus`. Это **два разных объекта-модуля** одного файла, классы `EventBus` не идентичны. Мутации файла бьют оба, но `isinstance`-сравнения между путями сломались бы
 - **Почему не здесь:** FR-026 — дефекты production-кода фиксируются отдельными задачами, а не правятся в фиче о тестах
 - **Статус:** Не исправлено


### #40 — `POST`/`GET`/`DELETE .../access` не проверяют существование устройства вопреки контракту · Low
*(выявлено 2026-10-04, спека 009, приёмка после снятия пропусков #38)*
 - **Файлы и строки:** `src/webui/routes/devices/access_control.py:82-158` (`grant_device_access` — проверки устройства нет ни до, ни после `grant_access`), `:161-218` (`revoke_device_access`), `:221-265` (`get_device_access_list`); обещание 404 — в докстринге `:107` и `:242`. Контракт: `specs/004-device-access-control/contracts/access-control-api.md:13`, `:44` («Устройство не найдено → 404») и `:52` («200: массив записей…; 404 если устройство не найдено»). Сервисный слой: `src/services/device_service.py:976-977`
 - **В чём проблема — измерено на фиктивном `uuid4()`:** `POST /api/v1/devices/{uuid4()}/access` от администратора отвечает **201** и сохраняет запись о доступе к несуществующему устройству; `GET` по тому же пути отдаёт **200** с этой записью вместо 404; `DELETE .../access/{id}` отзывает её (**204**). Ровно то же обещает докстринг роута, и ровно то же отрицает контракт. Записи при этом **не осиротевают**: они остаются в `device_access.json` и всплывают, когда устройство появится
 - **Чем обнаружено:** инъекция фиктивного идентификатора в фикстуру вместо реального устройства. 7 тестов управления записями доступа в `tests/contract/test_access_control.py` остались зелёными — то есть контракт прав на несуществующем устройлении проходил проверку. Отдельно подтверждено `POST` → 201 и `GET` → 200 на пустом `uuid4()`
 - **Почему раньше не проявлялось, в два слоя.** (1) До снятия guards `pytest.skip` (Known Issue #38) тесты закрывались условием, которое не срабатывало: подготовка была исправна, guards молчали, и наличие устройства ничем не гарантировалось. (2) После снятия guards фикстура всё ещё создавала **настоящее** устройство, поэтому сценарий «устройства нет» просто не возникал — потребовалась отдельная инъекция, чтобы дойти до него
 - **Существенное уточнение: поведение намеренное, расходится документация.** `specs/004-device-access-control/tasks.md:117` фиксирует сознательное отклонение: «порядок проверок — существование (404) ДО доступа (403)… grant стал **device-blind** (снят device-existence-требование в `DeviceService.grant_access` — доступ выдаётся на идентификатор до синка; отклонение от «сервис не менять», диктовано acceptance)». Логика сервиса это подтверждает — `device_service.py:976-977`: «Устройство может не существовать ещё (grant до синка) — доступ выдаётся на идентификатор устройства (device-blind)». То есть `201` на несуществующем устройстве — **не баг, а принятое решение**; баг в том, что отклонение не доведено до контракта и до докстрингов, и что оно не распространялось на `GET` списка доступов, для которого санкции не было вовсе. Это же отмечено в `specs/009-test-coverage/tasks.md:118` (T008): тест на назначение доступа несуществующему устройству переписан под фактическое поведение
 - **Что требуется решить (выбор за властями продукта, не в этой фиче):** либо привести `access-control-api.md:13,44,52` и докстринги `:107`, `:242` в соответствие с принятым device-blind решением, либо вернуть проверку существования в `grant_device_access` и `get_device_access_list`. Второе меняет принятое на acceptance поведение и затронет сценарий «доступ до синка»
 - **Статус:** Не исправлено (FR-026 — дефект production-кода и расхождение контракта фиксируются отдельной задачей; здесь зафиксировано измерение)


### #41 — `GET /api/v1/devices` игнорировал `X-Is-Admin`, хотя шесть соседних эндпоинтов его учитывают · Low
*(выявлено 2026-10-04, спека 009, тот же прогон инъекций; исправлено 2026-10-04, спека 009)*
 - **Файлы и строки (после правки):** `src/webui/routes/devices/devices.py:127-190` (`get_devices`), `:43-59` (`_is_admin_request` — новая единая точка чтения признака), `:62-97` (`_require_access_or_403`, обход админа `:81-82`), `:781-782` (`POST /apply` — см. «Оставшееся»). Сервисный слой: `src/services/device_service.py:446-458` (`list_devices`, источник истины — `get_all_devices` `:438-444`), `:1079-1108` (`get_user_accessible_devices`, ветка не-админа). До правки те же места были `:111-163` и `:43-81`, где признак читался прямо в `_require_access_or_403` строками **65-66**; второе место чтения списка — `src/webui/routes/__init__.py:307-309`
 - **В чём был дефект.** Список строился **только** из записей доступа: `x_user_id` → `load_accesses_for_user` → `get_device` для каждой записи. Заголовок `X-Is-Admin` в `get_devices` **не читался вовсе** — в сигнатуре только `x_user_id`. Администратор, который только что применил устройства через `POST /devices/apply`, видел их (записи выдаются), но администратор без записей — включая только что развернувшуюся установку — получал `[]`
 - **Почему дефект, а не замысел — решающий аргумент: расхождение видно в типовой установке.** Второе место чтения списка, `src/webui/routes/__init__.py:307-309`, admin-обход **учитывает** (`if is_admin: return None` — без фильтрации). То есть в web-слое обход для списка есть, а в API-роуте — нет. При этом дефолтная идентичность самого WebUI — администратор (`src/webui/app.py:33,36`: пользователь `admin_user`, `X-Is-Admin: true`), то есть **собственный интерфейс платформы в типовой установке запрашивал список без единого grant-а и получал `[]`**. Наблюдаемый симптом безо всякой теории. Плюс асимметрия внутри модуля: `_require_access_or_403` даёт администратору безусловный обход, и им пользуются шесть эндпоинтов (`GET /devices/{id}`, `DELETE /devices/{id}`, `PUT .../config`, `POST .../command`, `GET .../command/{id}`, `GET .../events`), а список был единственным, кто этот обход не разделял — в одном модуле действовали **два противоречивых правила** «кто имеет право видеть устройство». Внешне это читается однозначно: одиночный `GET /devices/{id}` администратору проходит (200), а `GET /devices` для того же администратора — пустой
 - **Контракт требует обратного, а не молчит.** `specs/004-device-access-control/data-model.md:38` — `get_user_accessible_devices` = «устройства с выданными доступами **(admin → все)**»; `spec.md:128` — «Администратор — глобальный: имеет доступ **ко всем** endpoints устройств; персональные записи доступа ему не нужны»; `research.md:31` — сервисный метод «уже существует и **покрывает роль admin (все устройства)**»; `contracts/access-control-api.md:16` — `X-Is-Admin: true` → глобальный админ, а раздел §2 контракта посвящён именно `GET /api/v1/devices`. То есть при обосновании решения R3 премисса была признана **ложной**: метод админа не покрывает
 - **Чем обнаружено:** устройство, посеянное напрямую в `DeviceService` через `tests/helpers/device_factory.py::seed_device_in_service`, читается одиночным `GET /devices/{id}` → **200**, но в `GET /api/v1/devices` отсутствует. Из-за этого **подготовка проверялась одиночным чтением, а не списком**: `tests/contract/test_devices_api.py:160-165` вынужден делать пробный `GET /devices/{id}` после посева, иначе тесты ниже получали бы 404 и проверяли бы контракт 404 вместо контракта устройства
 - ~~**Подтверждение со стороны приложения через quickstart.**~~ **АТРИБУЦИЯ ОПРОВЕРГНУТА, пункт удалён.** Ранее здесь было записано, что дефект объясняет 4 из 7 падений в `tests/validation/validate_quickstart.py`. Это **неверно**: скрипт создаёт `TestClient(app)` без заголовков по умолчанию (`validate_quickstart.py:192-196`) и запрашивает список со свежим `X-User-ID = str(uuid4())` и **без `X-Is-Admin`** — в файле нет ни одного упоминания `X-Is-Admin`. Это запросы не-администратора без единого grant-а, и пустой список там предписывается контрактом (`access-control-api.md:20-21`). Реализация admin-обхода в списке не изменила ни одну из этих проверок. Причина падений — скрипт авторизует каждый сценарий свежим случайным пользователем, это зона #42
 - **Что сделано** (правка только в `src/webui/routes/devices/devices.py`). (1) Заведён `_is_admin_request` — ровно то выражение, что было в `_require_access_or_403` (`request.state.is_admin` с фоллбэком на заголовок `X-Is-Admin`), вынесено в отдельную функцию как единая точка чтения признака; `_require_access_or_403` теперь вызывает её, поэтому поведение шести эндпоинтов **не изменилось** — новой логики доступа не появилось, устранено её дублирование. (2) В `get_devices` признак читается **до** проверки `X-User-ID` — так же, как в `_require_access_or_403`, где обход админа (`:81-82`) тоже идёт раньше требования `user_id` (`:83`). Админ → `list_devices()` (полный набор без чтения записей), остальные → прежний `get_user_accessible_devices`. (3) Фильтр `source_id` остался **один** и применяется поверх в обоих случаях (`:179-180`). Для администратора он теперь работает по-настоящему: прежний довод «поверх фильтра доступа без записей фильтр бесполезен, он всегда даёт `[]`» после правки неприменим — фильтр сужает настоящий список. (4) Докстринг переписан: прежний утверждал, что список всегда строится из записей доступа, то есть документировал дефект; теперь в нём обе ветви и ссылки на `spec 004 spec.md:128`, `data-model.md:38`
 - **Почему `list_devices()`, а не `get_all_devices()` напрямую.** Источник истины — `get_all_devices` (`device_service.py:438-444`), но вызван `list_devices` (`:446-458`), чтобы фильтр `source_id` остался в одном месте — в роуте, одинаковом для обеих ветвей. Дублирование фильтрации в сервисе и в роуте дало бы два места, расходящихся при правке
 - **Тесты:** `tests/contract/test_device_list_admin_bypass.py`, 5 тестов в двух классах. `TestAdminListBypass` (3): админ без единой записи видит устройство; админ видит и с записью, и без неё (доступ выдан **другому** пользователю); фильтр `source_id` сужает список админа, а не игнорируется. `TestNonAdminListFiltering` (2, страховка от обратной ошибки): не-админ без доступа → `[]`; с выданным доступом → ровно своё устройство. Предусловие фикстуры **проверяется, а не предполагается**: оба устройства посеяны прямо в `DeviceService` (в двух разных источниках — иначе фильтр `source_id` не отличить от «показал всё»), каждое читается одиночным `GET /devices/{id}` → 200, и у каждого `GET .../access` возвращает `[]`. Без такой проверки пустой список можно было бы объяснить либо отсутствием устройства, либо наличием записи. Администратор в тестах намеренно `chief_admin`, а не `admin_user`. Отдельный клиент на запрос обязателен: httpx **сливает** заголовки запроса с дефолтными заголовками клиента, а не заменяет их, — переопределение одного `X-User-ID` оставляло бы `X-Is-Admin: true`, и не-админ получал бы admin-bypass (та же ловушка, что в T024–T029)
 - **Чувствительность доказана тремя мутациями production-кода** (все откачены): убран админский обход → падают 3 админских теста; админ получает пустой список → падают те же 3; убрана фильтрация по записям у не-админа → падают 2 страховочных. То есть обход проверен и на отсутствие ложного срабатывания, и на ослабление прав — обе стороны, а не одна
 - **Ловушка, из-за которой дефект держался зелёным: `test_admin_sees_all_devices` (`tests/contract/test_device_access_rights.py:153`) был зелёным на сломанной реализации.** Устройства там появляются синхронизацией источника, а `DeviceService._grant_sync_access` (`src/services/device_service.py:217-234`) сама создаёт запись доступа для жёстко зашитого `SYNC_ACCESS_USER = "admin_user"` (`:46`), и админ в тестах тоже `admin_user`. То есть он видел устройства **по записи доступа**, а не по `X-Is-Admin`: обход администратора проверялся ровно тем способом, который обход не проверяет. Отличить одно от другого можно только устройством **без единой записи доступа** и администратором с **другим** именем — поэтому проверки вынесены в отдельный файл: два разных предусловия в одном наборе читались бы как одно. Прежний тест правкой не тронут
 - **Одно намеренное изменение сверх буквального дефекта: `X-Is-Admin: true` без `X-User-ID` теперь тоже даёт полный список.** Это следует из `spec.md:128` («персональные записи доступа админу не требуются») и из порядка проверок в соседней функции, где обход админа идёт раньше требования `user_id`. В контрактной строке `contracts/access-control-api.md:20` («Без `X-User-ID` → пустой список») это **исключение для администратора**; анонимный запрос по-прежнему получает `[]`
 - **⚠️ Незакреплённый случай:** этот `X-Is-Admin` без `X-User-ID` **новыми тестами не закрыт** — в `test_device_list_admin_bypass.py` теста на него нет. Требуется либо тест, либо явная оговорка в контракте, что строка `:20` описывает только не-администратора
 - **Оставшееся — задача не решала, не исправлено: `POST /api/v1/devices/apply` без проверки прав при обещании 403.** Это утверждение **не подтвердилось при проверке 2026-10-07**: запрет есть — `apply_devices` объявлен с `Depends(require_admin)` (`src/webui/routes/devices/devices.py:938`), и докстринг `:955` его обещает честно. Запись писалась 2026-10-04 и ссылалась на номера строк, сдвинувшиеся после фикса #41 в том же модуле; перепроверять такие утверждения следует до планирования работы по ним
 - **Что осталось верным:** правил доступа в модуле действительно три (общий обход админа через `_is_admin_request`, видимость списка по признаку админа иначе по записям, админский запрет на применение), и три правила в одном месте — повод для отдельной правки на будущее
 - **Проверка вживую** (приложение на временном каталоге, устройство посеяно без записей доступа): WebUI (`admin_user`, `X-Is-Admin: true`) → 200, полный список; тот же пользователь без `X-Is-Admin` → `[]`; аноним → `[]`; только `X-Is-Admin`, без `X-User-ID` → полный список
 - **Статус:** ✅ **ИСПРАВЛЕНО 2026-10-04** (спека 009). Правка ограничена одним production-файлом `src/webui/routes/devices/devices.py` плюс новый тестовый файл; незакрытыми остаются два пункта, помеченные выше


### #42 — Два ручных скрипта вне CI падают; один из них ещё и пишет артефакт в корень репозитория · Low
*(выявлено 2026-10-04, спека 009 T014)*
 - **Файлы:** `tests/security/verify_logging.py`, `tests/validation/validate_quickstart.py`
 - **Проверка фактов (запущено явно, не на словах).** Оба файла — pytest-модули, но имена не матчат `python_files = test_*.py` (в `pyproject.toml` не переопределён), поэтому `pytest tests/` их **не собирает**: `pytest tests/ --collect-only` даёт 0 совпадений. Ни `Makefile`, ни `.github/workflows`, ни `run_checks.sh` их не упоминают — то есть **красный код никто не видит**. Прямой `python3 <файл>` не делает ничего (это не скрипты с `__main__`, выход 0); запускать надо pytest
 - **`verify_logging.py`: 1 failed / 5 passed.** `tests/security/verify_logging.py::test_context_fields` — `AssertionError: Лог sync_devices отсутствует device_id`. Остальные 5 тестов файла проходят
 - **`validate_quickstart.py`: 1 failed / 6 passed**, и он **пишет `validation_report.md` в корень репозитория**. `test_all_scenarios_with_report` падает на `tests/validation/validate_quickstart.py:1444` — `assert failed_checks == 0` → `AssertionError: Валидация не пройдена: 7 ошибок` (10 из 17 проверок пройдено, 1 из 6 сценариев успешен). Запись файла — `validate_quickstart.py:1421-1423`: `report_path = Path(__file__).parent.parent.parent / "validation_report.md"`, то есть путь от трёх уровней вверх, а **не** во временный каталог
 - **Почему это дефект процесса, а не «просто красный тест».** (1) Нарушается сценарий 9 quickstart — после прогона `git status` перестаёт быть пустым: артефакт появляется как `?? validation_report.md` в корне. (2) Нарушается FR-026 / SC-016 спеки 009 — тест не имеет права оставлять за собой файлы в репозитории. (3) Путь считается от расположения файла, а не от `tmp_path`, поэтому из другого расположения он указал бы не туда. (4) Красные тесты, которых нет ни в одной проверке, — прямое продолжение находки #30 (`tests/security/verify_security.py` в том же состоянии), то есть проблема тиражирована и никуда не исчезла после T011a
 - **Что сделано при разведке:** артефакт удалён, `git status --short` возвращён к исходному состоянию (5 изменённых тестовых файлов, ничего постороннего). Ни один из скриптов не запускается в проверках качества, поэтому в прогон `pytest tests/` они не попадают и BaselineSpecs 009 «1996 passed» не затрагивают
 - **Статус:** Не исправлено (требуется решение: перенос пути отчёта во временный каталог + включение обоих файлов в перечень проверяемых либо явная пометка «ручной, не гейтится»)


### #43 — Тесты пишут в `data/` репозитория неатомарно — два параллельных прогона портят друг другу состояние · Low
*(выявлено 2026-10-04, спека 009, при разборе «порядковой зависимости» в `test_devices_api.py`)*
 - **Файлы:** `src/core/persistence/devices.py:213-224` (`save_device_config`: `open(..., "w")` с последующим `json.dump` — файл усекается до записи, атомарной замены нет), `:197-211` (`_load_devices_data` с `except json.JSONDecodeError` → «Файл … повреждён, начинаю с пустого»); путь `PersistenceManager(data_dir="data")` — `src/webui/app.py:367`, относительный и разрешаемый от текущего каталога. Пересечение с #28 (тесты пишут в `data/`), но дефект здесь другой — не в накоплении мусора, а в порче состояния
 - **В чём проблема.** Прогоны, берущие синглтон `from src.main import app`, пишут в общие `data/*.json` read-modify-write без блокировок. Два процесса pytest, работающие одновременно, теряют записи друг друга и читают **наполовину записанный** JSON. Наблюдаемая сигнатура в логе: `WARNING src.core.persistence.devices:devices.py:210 Файл data/devices.json повреждён, начинаю с пустого`
 - **Чем обнаружено и как воспроизведено.** Заявленная «внутрифайловая порядковая зависимость» в `tests/contract/test_devices_api.py` (в одиночку 23 passed, в каталоге 5 failed) **не подтвердилась**: 40 последовательных прогонов `tests/contract/` дали `116 passed` каждый, полный прогон — `1996 passed`. Расхождение воспроизвелось **только** при двух параллельных процессах. Типичные падения: `StopIteration` в `TestDeviceDeleteAPI._applied_device` (`test_devices_api.py:411` — применённое устройство не попало в список, потому что чужой процесс переписал `devices.json`); `test_access_control.py:98` «созданный источник не читается обратно: 404» (источник получен 201, но уже стёрт другим прогоном); `test_access_control.py:392` «дубликаты записей: []»; `test_sources_api.py:280` и `test_device_events_api.py:184` (`assert 404 == 200`, `assert 403 == 200`). Один прогон каталога в сумме давал до 3 failed + 5 errors. Проверено 6 параллельных пар: 5 из 6 прогонов `tests/contract/` упали, 1 из 6 одиночных прогонов `test_devices_api.py` упал
 - **Почему это не.order-зависимость внутри файла.** `POST /devices/apply` идемпотентен по `ha_entity_id`: повторный apply того же идентификатора возвращает **тот же** `device_id`. Проверено прямо — после неудачного удаления (403) оставшееся устройство переиспользуется следующим apply, и `_applied_device` возвращает именно его; дубликатов с одним `ha_entity_id` не накапливается. Поэтому остаточные устройства от тестов с 403/401 не создают связности между тестами
 - **Почему опасно.** Ошибка недетерминирована и выглядит как «капризный тест»: её воспроизведение требует двух прогонов, поэтому её обычно списывают на порядок или на чужой код. При этом она уже маскировала настоящие дефекты — в прогоне, где один процесс чинит, другой получает ложную картину. В CI не проявляется: `xdist` не используется ни в `Makefile`, ни в `.github/workflows`, ни в `pyproject.toml`, прогоны последовательные. Опасно для разработчика, который держит вторую вкладку с `pytest -x` или для будущего перехода на `-n auto`
 - **Статус:** ✅ Исправлено в specs/009 (`a7fe338`): тесты переведены на изоляцию через явный `DATA_PATH` в каждой фикстуре, а не через относительный путь и `os.chdir`. Параллельные прогоны более не делят каталог данных


### #44 — Данные не переживают пересоздание контейнера: `DATA_PATH` не читается кодом · Low
*(выявлено 2026-10-04, аудит перед продакшеном; **доказано фактическим запуском контейнера`)*
 - **Где:** объявлен в `deploy/docker/Dockerfile:14` и `deploy/docker/docker-compose.prod.yml:42` (`DATA_PATH=/data/behavioral_platform`), том `./data:/data/behavioral_platform:rw` в `compose:49`. Но `grep -rn "DATA_PATH" --include="*.py"` даёт **ноль совпадений** — переменную не читает ни одна строка Python. Все хранилища берут относительный путь по умолчанию: `src/core/persistence/devices.py:25`, `sources.py:24`, `manager.py:20`, `migrations_runner.py:23`, `state_persistence.py:26` (`DEFAULT_DATA_DIR = "data"`), `event_store.py:54` (`db_path="data/history.db"`)
 - **Механика:** при `WORKDIR /app` (`Dockerfile:20`) относительный `data` разрешается в **`/app/data`** — внутри слоя контейнера. Том монтируется в `/data/behavioral_platform`, то есть **в другой каталог, который никто не использует**
 - **Доказательство фактическим запуском.** (1) `find deploy/docker/data -type f` до старта — пусто. (2) `docker compose up -d`, контейнер `healthy`, создание источника через API → `источников: 1`. (3) `docker exec behavioral-platform ls -la /app/data/` → `history.db` (45056 байт) и `sources.json` (542 байта); `ls -la /data/behavioral_platform/` → **пусто**. (4) `docker compose down && up -d` (ровно то, что делает деплой при обновлении образа) → `источников: 0`. **Данные потеряны**
 - **Последствие:** любое обновление образа, пересоздание контейнера или перезагрузка узла уничтожает всю конфигурацию установки — устройства, источники, права доступа, состояния, журнал. Том `./data` навсегда остаётся пустым, а **бэкапить нечего**, поэтому Блокер «бэкапа нет» (см. #39, `backup_service.py:22` — бэкапит HA, а не `data/`, и не вызывается нигде в production) теряет смысл до исправления этого пункта
 - **Почему не поймано 3 годами.** Проверка Docker в спеках 003/020 проверяла, что образ **собирается** и контейнер **стартует**, но не проверяла, что данные переживают пересоздание. А приложение, стартовавшее с пустым `data/`, считает себя исправным: `/health` возвращает константу `{"status":"ok"}` (`routes/__init__.py:99-112`), то есть Docker помечает контейнер здоровым при полной потере конфигурации
 - **Что сделать:** `DEFAULT_DATA_DIR = os.environ.get("DATA_PATH", "data")` во всех конструкторах хранилищ; **плюс регресс-проверка, запускающая контейнер** — тест на чтение кода эту ошибку не поймает, поскольку оба значения присутствуют в файлах. Порядок критичен: Блокер бэкапа и атомарной записи бессмысленны, пока данные не переживают контейнер
 - **Смежная находка в том же прогоне:** том `./config:/config/behavioral_platform` (`compose:47`) тоже не используется — `CONFIG_PATH` по умолчанию `/app/instances/leonids_house` (`compose:41`), а этот каталог **копируется в образ** (`Dockerfile:42`), то есть правки манифеста в контейнере теряются при пересоздании. Либо перемонтировать на `/app/instances`, либо убрать мёртвый том, чтобы он не вводил в заблуждение
 - **✅ Исправлено 2026-10-05.** Введён единый источник пути — `src/core/persistence/paths.py::resolve_data_dir()`: приоритет у явно переданного пути, затем `DATA_PATH` из окружения, затем `"data"` (прежнее поведение). Разрешается **в момент вызова**, а не на импорте, иначе подмена переменной в тестах не имела бы эффекта. Переведены `DevicePersistence`, `DeviceAccessPersistence`, `DeviceSyncEventPersistence`, `HASourcePersistence`, `PersistenceManager`, `StatePersistence.default_storage_path`, `EventStore` и миграции (`migrations_runner`, `db_init`, `001_init_sources`, `002_init_devices`, `index_manager`)
 - **Вторая половина, без которой правка не сработала бы:** `webui/app.py:379` создавал `PersistenceManager(data_dir="data")` — **явный** аргумент, который перекрывает переменную. После исправления конфигурации `history.db` уезжал в том, а `sources.json` оставался в `/app/data`, то есть дефект выглядел исправленным наполовину. Явный путь убран
 - **Доказательство в контейнере:** образ пересобран, `docker compose up -d`, источник создан через API. Каталог `/app/data` **не создаётся вовсе**, `history.db` и `sources.json` лежат в томе `./data`. Далее `docker compose down && up -d` → источников **1** (до правки было 0); `docker restart` → источников **1**
 - **Тесты:** `tests/unit/core/test_data_dir_resolution.py`, 21 тест. Проверка на чтение кода бессильна — литерал `"data"` и `DATA_PATH` могут сосуществовать, поэтому есть исполняемые проверки (каждое хранилище создаётся и его путь сверяется с `DATA_PATH`) **и** механический запрет: параметризованный тест на отсутствие `= "data"` в семи модулях персистентности плюс проверка, что литерал живёт только в `paths.DEFAULT_DATA_DIR`
 - **Чувствительность доказана тремя инъекциями:** возврат литерала `data` в `DevicePersistence` → 4 теста падают; возврат `PersistenceManager(data_dir="data")` в `app.py` → падает тест на явный путь; `resolve_data_dir`, игнорирующий `DATA_PATH` → 9 тестов падают. Всё откачено побайтово
 - **Статус:** ✅ Исправлено в specs/009 (коммит с этой правкой)


### #45 — Три бага приложения, найденные включением проверок mypy · Low
*(выявлено 2026-10-04, спека 009, при разборе `disable_error_code`)*
 - **Почему нашлись только сейчас.** `disable_error_code` в `pyproject.toml` отключал 16 кодов, включая `attr-defined`. Именно из-за этого исторический баг `from core.fsm import FSMEngine` в `export_fsm.py` молча проходил месяцами. Коды корректности включены, mypy дал 119 ошибок — и три из них оказались настоящими багами, а не шумом
 - **`webui/routes/__init__.py:591` — принятие и отклонение AI-предложений молча теряются.** Маршрут шлёт `status="accepted"`/`"rejected"`, а `EventStore.update_suggestion_status` (`event_store.py:378-413`) обрабатывает **только** `"applied"`, `"dismissed"`, `"snoozed"`. Ни одна ветка не срабатывает, `UPDATE` не выполняется, `conn.commit()` выполняется, эндпоинт отвечает `{"status": "success"}`. **Проверено на реальном SQLite:** `total_changes == 1` (только INSERT), строка не меняется. То есть каждое принятие и отклонение предложения отбрасывается без ошибки
 - **`core/manifest_generator.py:104` — переход по движению недостижим.** `from_state=("OFF", "ON_SCHEDULE")` — кортеж, тогда как `Transition.from_state` объявлен `str` (`definitions.py:31`), а движок сравнивает `transition.from_state == state.current_state` (`engine.py:428, 651`). Кортеж никогда не равен строке, поэтому `motion_detected` не срабатывает ни из OFF, ни из ON_SCHEDULE. Освещение не включается по движению для сгенерированных манифестов
 - **`webui/app.py:344` + `core/discovery/discovery_service.py:136` — AttributeError без `HA_TOKEN`.** `Container.adapter` возвращает `MockAdapter`, у которого **нет** свойства `is_connected` (проверено: свойство отсутствует в `mock_adapter.py`), а `scan_devices` читает `self._ha_adapter.is_connected`. В любом окружении без настроенного `HA_TOKEN` все `/discovery/*` отдают 500. То есть визард обнаружения устройств не работает из коробки
 - **Плюс два отброшенных как ложные:** `scheduler.py:127` (`task.cancel()` под guard — mypy не видит инвариант через границу метода) и `context_manager.py:124,188` (объявление `_context: dict[str, dict]` было просто неверным — туда пишутся `bool`; шум возник из-за объявления, а не из-за кода)
 - **Найдено дополнительно, вне рамок mypy:** `services/logging_service.py:517` — вызов `initialize(log_dir=...)`, которого у метода **нет** (параметр есть только у `__init__`), то есть гарантированный `TypeError`; функция нигде не вызывается, поэтому не заметно. И `device_service.py:578` — `self.persistence.device_access.delete_accesses_for_device(...)` без guard, тогда как строка выше проверяет `persistence` на `None`; достижимо, когда `PersistenceManager` не импортировался (`app.py:368` логирует «Running with limited functionality»)
 - **Статус:** ✅ Исправлено в specs/009 (2026-10-05), все три: решения по AI-предложениям (`routes/__init__.py` шлёт теперь термины хранилища, а `update_suggestion_status` поднимает `ValueError` на неизвестный статус вместо молчаливого `commit()`); переход по движению (кортеж развёрнут в два перехода); `MockAdapter.is_connected` (заглушка честно сообщает `False`, `scan_devices` читает через `getattr`). Плюс `logging_service.py:517` и `device_service.py:578`. См. также #46


### #46 — Guard'ы, генерируемые манифестом, не принимались движком · Low
*(выявлено 2026-10-05 при исправлении #45, спека 009)*
 - **Файлы:** `src/core/manifest_generator.py` — 11 лямбд в `_generate_lighting`, `_generate_climate`, `_generate_ventilation`
 - **В чём проблема:** движок вызывает guard как `guard_fn(state, context)` (`core/fsm/engine.py:489`), то есть **первым** позиционным аргументом приходит объект `State`. Лямбды были объявлены как `lambda ctx, r=room: ctx.get(f"{r}_motion_sensor", False)`, поэтому в `ctx` оказывался `State`, у которого **нет метода `.get`** (проверено: `hasattr(State, "get") == False`). Результат — `AttributeError` внутри guard'а, который `_evaluate_guard` перехватывает и **отклоняет переход**
 - **Почему это хуже молчаливого отказа:** упавший guard выглядит как «условие не выполнено», поэтому переход просто не срабатывает — без ошибки, без лога об ошибке (только `Guard '<lambda>' raised exception` на уровне ERROR). Итог: **ни один переход, читающий контекст, не работал** — освещение по движению, климат по температуре, вентиляция по влажности, таймаут ручного управления
 - **Связь с #45:** баг с кортежем в `from_state` и этот — независимые. Даже после исправления кортежа переход не срабатывал: guard падал раньше, чем проверялось состояние. Оба пришлось починить, чтобы движение заработало
 - **Дополнительно вскрыто:** в логах постоянно встречается `Guard 'is_day_time' not found in registry` и `Guard 'is_manual_override_enabled' not found in registry`, но **ни одного guard'а с такими именами в `src/` нет** — то есть генератор ссылается на несуществующие имена. Проверено `grep` по всему `src/`: пусто. Зарегистрирован только `is_night_time` (`core/registry.py:25`), и он тоже не используется генератором
 - **Статус:** ✅ Исправлено в specs/009 (сигнатуры приведены к контракту движка). Несуществующие имена guard'ов (`is_day_time`, `is_manual_override_enabled`) — отдельная находка, требует решения: либо реализовать, либо убрать ссылки


### #47 — Ключ шифрования токенов генерировался заново при каждом старте · Low
*(выявлено 2026-10-05 при проверке Блокара 1, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/core/security/encryption.py`, `src/core/persistence/sources.py`, `src/core/persistence/atomic.py`, `deploy/docker/.env.example`, `.gitignore`
 - **В чём была проблема:** если ключ не задан, он генерировался в памяти при каждом старте — токены становились недоступны. Хуже того, ошибка расшифровки глоталась, и токен безвозвратно разрушался: см. #53
 - **Доказательство исходного поведения:** в контейнере переменная не задана; два запуска подряд дали хеши ключей `30f7b31f32c1` и `501bac3adf46`, а шифротекст одного и того же токена различался
 - **ПРЕДЫДУЩЕЕ УТВЕРЖДЕНИЕ БЫЛО НЕВЕРНЫМ (исправлено 2026-10-05).** В этой же записи было сказано, что «в образе контейнера нет `cryptography`, поэтому токены пишутся открытым текстом», и что `cryptography` «объявлена в `pyproject.toml`, но отсутствует в образе». **Оба утверждения опровергнуты запуском контейнера:** `cryptography 50.0.2` в образе присутствует, токены действительно шифруются
 - **Что сделано — по решению владельца выбран вариант 2 (файл ключа в томе данных).** Приоритет источников: явный аргумент → `HOME_ASSISTANT_ENCRYPTION_KEY` → файл `ENCRYPTION_KEY_PATH` (по умолчанию `<DATA_PATH>/encryption.key`). Файл создаётся один раз, права `600`, записывается атомарно
 - **Права на файл выставляются ДО записи содержимого.** В `atomic_write_text` добавлен параметр `mode`; для ключа он равен `0o600`. Обратный порядок оставлял окно, в котором секрет доступен всем, кто читает каталог
 - **Существующий, но нечитаемый или пустой файл ключа — ошибка, а не повод сгенерировать новый.** Поднимается `EncryptionKeyError`. Иначе платформа продолжила бы работу с новым ключом и зашифровала старые значения повторно
 - **Проверено запуском контейнера:** ключ создан в томе с правами `600`; после `down && up -d` хеш ключа (`f2a55ba64286af35`) и значение токена не изменились, токен расшифровался в `MY_REAL_TOKEN_12345`. При потере ключа источник не загружается с явной ошибкой в логе, значение на диске **не переписывается**, а после возврата ключа источник снова появляется
 - **Тесты:** `tests/unit/core/test_encryption.py` — файл создаётся, переживает «перезапуск», не перезаписывается, права `600`, пустой файл даёт ошибку; `tests/unit/core/test_source_token_integrity.py` (новый, 6). Тест `test_generated_key_differs_between_instances` **закреплял дефект как норму** (утверждал, что ключи у экземпляров разные) — заменён на противоположное утверждение
 - **Чувствительность:** возврат `except ValueError` с подстановкой шифротекста → 3 теста падают; возврат генерации ключа в памяти → 6 тестов падают; снятие `mode=0o600` → тест на права падает с «ожидались права 600, получено 644»
 - **Статус:** ✅ Исправлено в specs/009


### #48 — Завершение платформы обрывалось на середине · Low
*(выявлено 2026-10-04 аудитом, исправлено 2026-10-05, спека 009)*
 - **Сторож не останавливался.** `Container.build()` запускал сторож через `_start_watchdog()`, но в `PlatformContext` его **не передавал** — поле `watchdog` оставалось `None`, поэтому условие `if self.watchdog is not None` в `shutdown()` было мёртвой веткой. При этом докстринг утверждал, что сторож останавливается, и он останавливается **первым**, поскольку читает состояния движка (FR-017). Фоновая задача переживала завершение и работала до SIGKILL, продолжая читать уже гаснущий движок
 - **Graceful shutdown зависал на WebSocket.** `uvicorn.Config` создавался без `timeout_graceful_shutdown`; дефолт uvicorn — `None`, то есть ожидание вечно. WS-ручки держат соединение бесконечным `await websocket.receive_text()`, поэтому при открытом `/ws/logs` или `/api/v1/ws/devices` завершение не наступало никогда. Docker по умолчанию ждёт 10 с и шлёт SIGKILL — `ctx.shutdown()` не выполнялся вовсе
 - **Тестов на `PlatformContext.shutdown()` и `run_platform()` не было вообще** — `grep` находил только `engine.shutdown()`. То есть критический путь завершения не был покрыт ничем
 - **Что сделано:** `build()` передаёт `watchdog=self._watchdog`; `uvicorn.Config` получил `timeout_graceful_shutdown=8`; в compose добавлен `stop_grace_period: 20s` (запас Docker больше таймаута uvicorn, иначе SIGKILL приходит раньше)
 - **Доказательство в контейнере:** `docker kill --signal=TERM` → остановка за **1 с**, `ExitCode=0` (не 137), `OOMKilled=false`. В логах появилась строка `watchdog:stop - Watchdog stopped`, которой до правки не могло быть, и `FSM Engine shutdown complete` — то есть цепочка отработала целиком
 - **Тесты:** `tests/unit/test_platform_shutdown.py`, 11 тестов. Проверяется не вызов `stop()`, а **результат**: после `shutdown()` задач `WatchdogService._watchdog_loop` в цикле не остаётся. Первая версия фильтровала задачи по подстроке `watchdog` в `repr(task.get_coro())` и находила **сам тест** — в его имени есть это слово, то есть проверка работала против себя; отбор исправлен на `_watchdog_loop` в `__qualname__`
 - **Чувствительность:** снятие `watchdog=` из `build()` → 6 тестов падают, включая живые задачи (`WatchdogService._watchdog_loop() running at watchdog.py:404`); снятие `timeout_graceful_shutdown` → падает 1; снятие `stop_grace_period` → падает 1
 - **Мелочь, не правил:** в логах завершения видно `Shutting down` дважды и `Waiting for application shutdown` дважды — похоже, `server.shutdown()` вызывается дважды. Код выхода при этом 0, цепочка отработала. Повод разобраться, но не блокер
 - **Статус:** ✅ Исправлено в specs/009


### #49 — Запись данных не атомарна; повреждённый файл молча затирался · Low
*(выявлено 2026-10-04 аудитом, исправлено 2026-10-05, спека 009)*
 - **Файлы (было):** `devices.py` — 10 мест, `sources.py` — 2, `manifest_store.py` — 2, `migrations/index_manager.py` — 2, `migrations/migrations_runner.py` — 1, `webui/app.py` — 1. Все писали через `open(..., "w")` + `json.dump`/`yaml.dump`, то есть файл **усекался до** записи
 - **Две беды вместе.** (1) Сбой питания в момент записи оставлял файл обрезанным или пустым — `fsync` не вызывался нигде. (2) При чтении повреждённого файла возвращался `{}` с единственной строкой `WARNING`, и **следующая же запись перезаписывала файл пустым состоянием** — данные исчезали бессрочно, без бэкапа и без копии
 - **Доказано до правки** на `DeviceSyncEventPersistence`: записать событие, испортить файл, записать ещё одно. В файле осталась **только новая запись**, исходное событие исчезло, рядом не было ни копии, ни следа. Единственное свидетельство — строка `WARNING` в журнале
 - **Шаблон решения был в проекте:** `StatePersistence` уже делал temp + `fsync` + `os.rename`. Но у него была своя ошибка — `flock` брался на **заменяемый inode**, поэтому взаимное исключение между вызовами не работало, хотя докстринг утверждал обратное
 - **Что сделано:** `src/core/persistence/atomic.py` — `atomic_write_json` и `atomic_write_text` (temp с уникальным именем → `flush` → `fsync` → `os.replace` → `fsync` каталога → очистка temp) и `PersistenceCorruptedError`. При `JSONDecodeError` файл **перемещается** в `<имя>.corrupt-<ts>` целиком, а вызывающий получает исключение вместо молчаливого `{}`. Переведены все семь модулей
 - **Почему при повреждении поднимается исключение, а не возвращается пусто.** Требование «не падать» оказалось несовместимо с требованием «не терять данные»: молчаливое чтение пустоты и есть путь к потере. Исключение останавливает вызывающий код, решение переносится к оператору, а данные остаются на диске
 - **Побочная находка:** `atomic_write_json` принимает `default=str`, поэтому несериализуемое значение **не роняет запись**, а превращается в строку. Первая версия теста на «неудачную запись» строилась на `TypeError` от такого значения и потому проходила на неатомарной реализации. Тест переписан: отказ имитируется на `os.replace`
 - **Дефект в собственной проверке:** первый тест «читатель никогда не видит усечённый файл» читал файл **после** завершения каждой записи, поэтому окно усечения не наблюдалось никогда и тест проходил даже на заведомо неатомарном коде — доказывал не то, что заявлял. Переписан на чтение **в момент** незавершённой записи (`json.dump` задерживается на середине, чтение из другого потока). На неатомарной реализации падает
 - **Доказательство в контейнере:** источник создан, контейнер убит **SIGKILL** (имитация сбоя питания, необратимо). `sources.json` после этого **валиден**, источников 1; после перезапуска API отдаёт тот же источник; в логах ноль Traceback. До правки тот же сценарий заканчивался бы пустым хранилищем
 - **Тесты:** `tests/unit/core/test_atomic_persistence.py`, 18 тестов — поведенческие (окно усечения через поток, отказ на `os.replace` не теряет прежнее, повреждение сохраняется целиком, повторные повреждения не затирают копии) и механические (параметризованный запрет `open(...,"w")` в шести модулях-писателях)
 - **Чувствительность:** возврат `open("w")` в `devices.py` → падает механическая проверка; запись по месту вместо temp + `os.replace` → падают 2 теста, включая «читатель не видит усечённый файл». Стабильность: 5 прогонов подряд
 - **Статус:** ✅ Исправлено в specs/009


### #50 — Замок StatePersistence был на заменяемом inode; fsync выполнялся в event loop · Low
*(выявлено 2026-10-05 при доработке Блокера 2, спека 009)*
 - **Файлы:** `src/core/persistence/state_persistence.py`, `src/core/fsm/engine.py:697`, `src/core/persistence/atomic.py`
 - **Ошибка 1 — замок не работал.** `fcntl.flock` вызывался на **самом файле состояний**, который тут же подменялся `os.rename`. После подстановки нового inode замок оказывался на файле, которого больше нет, — взаимное исключение исчезало уже после первой записи, хотя докстринг утверждал: «Uses file locking to prevent race conditions». То есть read-modify-write состояний был не защищён
 - **Ошибка 2 — блокировка event loop.** `save_state` синхронный и делает `fsync`, а `FSMEngine` вызывал его прямо из корутины перехода (`engine.py:697`). Каждый переход автомата останавливал цикл на время записи; при нескольких автоматах это складывалось в задержки на WebSocket и ложные срабатывания сторожа
 - **Что сделано:** добавлен `file_lock` — взаимное исключение через отдельный файл `<данные>.lock`, чей inode постоянен и который никогда не подменяется. `StatePersistence.save_state` и `_save_data` переведены на общий `atomic_write_json` и новый замок, ~60 строк дублирования удалено. Добавлен `save_state_async` (`asyncio.to_thread`), движок вызывает его при наличии, иначе откатывается на синхронный путь — чтобы не сломать сторонние реализации сохранения
 - **Ошибка в моей же правке, найденная тестами:** пустой файл стал считаться повреждением. Но пустой файл — законное состояние: свежая установка либо файл, обрезанный до нуля сбоем питания. Считать это повреждением означало бы, что чистая установка падает с ошибкой и оператор обязан вручную удалять файл ради пустого хранилища. Теперь «пусто» отличается от «испорчено»
 - **Три теста в `tests/test_state_persistence.py` были привязаны к старому механизму** через `@patch` на `_acquire_lock`/`_release_lock` и на `fcntl`. Переписаны на поведение: отдельный файл замка, постоянство его inode, сохранение предыдущей записи. Тест `test_handles_corrupted_json_file` требовал «работать несмотря на битый файл» — то есть закреплял затирание как норму; заменён на требование сохранить файл и поднять ошибку
 - **Тесты:** `tests/unit/core/test_state_persistence_atomic.py`, 11. Конкуренция проверена **настоящими потоками** с барьером: 12 параллельных записей обязаны сохранить все 12 сущностей; плюс проверка, что `file_lock` действительно исключающий (четыре потока, подсчёт входов). Блокировка event loop проверяется счётчиком задач, растущим во время сохранений
 - **Чувствительность:** возврат замка на файл данных → 2 теста падают; превращение `save_state_async` в синхронный вызов → падает тест на event loop; запрет пустого файла как «пустого» → 4 теста падают
 - **Статус:** ✅ Исправлено в specs/009


### #51 — Скрипт качества и хук mypy проверяли не тот код, что CI · Low
*(выявлено 2026-10-05 при доработке Блокера 2, спека 009)*
 - **Файлы:** `.ai/scripts/run_checks.sh:142`, `.pre-commit-config.yaml`, `AGENTS.md:20`, `.ai/06_QUALITY_CHECKS.md:59`
 - **Ошибка 1 — ложный зелёный свет в скрипте качества.** Стояло `mypy src/ --strict --ignore-missing-imports`. Флаг `--ignore-missing-imports` превращает ненайденный импорт в тишину, а модуль без типов информации — в `Any`, вместе с ним исчезают и проверки обращений к его атрибутам. **Доказано инъекцией:** временный файл с импортом несуществующего пакета — с флагом `Success: no issues found`, без него `Found 1 error`. То есть `run_checks.sh` мог отметить успехом код, который CI отвергает. С тем же флагом молча прошла бы и нехватка зависимости в образе — ровно случай Known Issue про отсутствующий `cryptography`
 - **Ошибка 2 — хук mypy был нерабочим.** `mirrors-mypy` выполнялся в изолированном окружении с `additional_dependencies` из трёх пакетов; там нет `aiohttp`, `uvicorn`, `watchdog`, `websockets`, `prometheus_client`, `dotenv`, `cryptography`, поэтому хук всегда падал с 20 ошибками `import-not-found` — то есть фактически отключал проверку и подталкивал к `--no-verify`, что запрещено правилами проекта. Плюс `rev: v2.3.1` расходился с версией mypy из окружения
 - **Что оказалось неправдой в аудите:** утверждение «CI запускается с `--ignore-missing-imports`, хотя `AGENTS.md` требует `--strict`». В CI (`ci.yml:20`) флага нет — команда `mypy src/`, а `strict = true` задан в `pyproject.toml:106`. Неправдой было и то, что флаг нужен руками: он включается конфигурацией
 - **Что сделано:** `run_checks.sh` теперь выполняет `mypy src/`; хук переведён на `repo: local` с `language: system` и вызывает ровно ту же команду; `AGENTS.md` и `.ai/06_QUALITY_CHECKS.md` приведены в соответствие, в последнем добавлено предупреждение про `--ignore-missing-imports`. Теперь Makefile, CI, `run_checks.sh` и хук запускают одну проверку
 - **Статус:** ✅ Исправлено в specs/009


### #52 — Правки конфигурации молча откатывались при пересоздании контейнера; два файла конфигурации с разными значениями; резервная копия брала не тот каталог · Low
*(выявлено 2026-10-05 при проверке развёртывания, спека 009)*
 - **Файлы:** `deploy/docker/docker-compose.prod.yml`, `deploy/docker/Dockerfile`, `deploy/docker/docker-entrypoint.sh` (новый), `deploy/docker/.env.example` (новый), `deploy/scripts/deploy.sh`, `.gitignore`, `.dockerignore`
 - **Ошибка 1 — конфигурация была вне тома.** `CONFIG_PATH` указывал на `/app/instances/leonids_house` — каталог в слое контейнера, тогда как том монтируется в `/config/behavioral_platform`. Последствия: каталог тома `./config` на хосте был пуст, а правки манифеста из интерфейса откатывались при каждом пересоздании. **Доказано хешем файла:** `d5c0f6be…` (исходный) → `743f2a2d…` (после правки) → снова `d5c0f6be…` после `down && up -d`
 - **Ошибка 2 — три разных пути конфигурации.** `Dockerfile:13` задавал `/config/instances/leonids_house`, compose — `/app/instances/leonids_house`, а `deploy/README.md` и `deploy/.env.example` — `/config/behavioral_platform`. Ни один не совпадал с другим, и два из них не были смонтированы. Имя каталога `leonids_house` было зашито в пути развёртывания
 - **Ошибка 3 — два файла конфигурации с разными значениями.** В `deploy/docker/` лежали и `.env` (автоматически читаемый Compose для подстановки `${...}`), и `.env.prod` (указанный в `env_file`). Блок `environment:` имеет приоритет над `env_file`, поэтому в контейнер попадали значения из `.env`, а `.env.prod` был мёртвой конфигурацией. **Доказано запуском:** в контейнере `HA_URL=192.168.2.10` (из `.env`), тогда как в `.env.prod` стоял `192.168.1.100`. Оператор правил `.env.prod` и не получал эффекта. Плюс `HA_TOKEN=${HA_TOKEN}` в `environment:` делал оболочку вторым источником истины: **доказано инъекцией** — `HA_TOKEN=INJECTED-TOKEN-SHOULD-WIN docker compose up -d` давал в контейнере именно инъекцию, а после удаления строки — значение из `.env`
 - **Ошибка 4 — `.env.prod` с живым токеном был в git.** Причина в `.gitignore`: строка `.env` без звёздочки не покрывает `.env.prod`. Теперь `.env*` с исключением `!*.example`
 - **Ошибка 5 — резервная копия сохраняла не то.** `deploy.sh` использовал `CONFIG_DIR="./config"` и `DATA_DIR="./data"` от корня репозитория, тогда как compose монтирует тома относительно своего каталога. **Доказано запуском `deploy.sh backup`:** каталога `./config` в корне нет, поэтому `manifest.yaml` в копию не попадал, а состояния копировались из протухшего `./data`, который платформа не использует
 - **Ошибка 6 — откат удалял живые данные до остановки сервиса.** `rollback` выполнял `rm -rf "$DATA_DIR"` и только затем `down`. Не проявлялось лишь потому, что путь вёл в неиспользуемый каталог. С настоящими путями контейнер продолжал бы писать в удалённый каталог, а восстановление перемешивалось бы с живыми записями
 - **Что сделано:** единый `CONFIG_PATH=/config/behavioral_platform` — точка монтирования тома, как и было заявлено в документации; `deploy/docker/.env` стал единственным файлом конфигурации, секретные переменные убраны из `environment:`; добавлен `docker-entrypoint.sh`, переносящий конфигурацию из образа в пустой том (bind-mount не наследует содержимое образа); `.env.prod` снят с отслеживания, заведён `.env.example`; `deploy.sh` строит пути от каталога compose-файла, а rollback останавливает сервис до восстановления, сохраняет текущее состояние в `pre_rollback_*` и отказывается работать с пустой копией; в `.gitignore` добавлены рабочие каталоги развёртывания; в `.dockerignore` возвращён скрипт старта (исключение сделано по содержимому каталога, т.к. Docker не заходит внутрь исключённого каталога)
 - **Проверка чувствительности:** правка манифеста, переживающая `down && up -d` (после починки `01d0d1f1…` сохранён, до починки откатывалась к `d5c0f6be…`); возврат строки `HA_TOKEN=${HA_TOKEN}` снова пропускает инъекцию из оболочки в контейнер; сборка падает с «not found», если скрипт старта не вернуть в контекст через `.dockerignore`
 - **Статус:** ✅ Исправлено в specs/009


### #53 — Без ключа шифрования токены не просто терялись, а разрушались на каждом перезапуске · Low
*(выявлено 2026-10-05 при разборе вариантов для #47, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/core/persistence/sources.py` (`load_source`, `load_all_sources`, `_decrypt_token`, `SourceTokenError`)
 - **Что считалось проблемой:** в #47 записано, что без ключа сохранённые токены «становятся нерасшифровыми». Это верно, но описывало только половину: происходило не разрушение, а **накопительное** разрушение
 - **Ошибка 1 — исключение проглатывалось в двух местах.** `load_all_sources` содержал `except ValueError: pass`, а `load_source` — `with contextlib.suppress(ValueError)`. При неудачной расшифровке источник создавался с **шифротекстом** в поле `token`, выглядел рабочим, и ни исключения, ни предупреждения не было
 - **Ошибка 2 — каждая запись шифровала шифротекст.** Дальше `save_source` вызывал `encrypt(ciphertext)`, то есть токен шифровался повторно; каждый перезапуск добавлял слой
 - **Доказано прогоном кода:** запись настоящего токена → на диске шифротекст; «перезапуск» с новым ключом → `load_all_sources` возвращает токен, не равный настоящему; повторная запись → на диске `Z0FBQUFBQnF3NDZGOUJ0…` вместо прежнего `Z0FBQUFBQnF3NDZGSXhz…`; `decrypt` даёт `ValueError`. Восстановление невозможно ни при каком ключе
 - **Почему это опаснее, чем кажется:** платформа продолжает работать, источник в списке, синхронизация падает с «не удалось подключиться к HA», и виной выглядит Home Assistant или сеть. Предупреждения нет нигде
 - **Что сделано:** оба места используют общий `_decrypt_token`, который при неудаче поднимает `SourceTokenError` с указанием имени источника и способа восстановления ключа. Источник не загружается и **не переписывается** — данные остаются целыми, ключ можно вернуть и продолжить работу
 - **Побочно исправлено сообщение об ошибке:** `Fernet` бросает `InvalidToken` с пустым текстом, из-за чего в лог попадало «Ошибка расшифровки токена: .». Теперь добавляется имя класса
 - **Проверка в контейнере:** при потере ключа источник исчезает из списка с явной ошибкой в логе, значение в `sources.json` остаётся побайтно прежним, после возврата ключа источник снова доступен
 - **Тесты:** `tests/unit/core/test_source_token_integrity.py`, 6. Чувствительность: возврат подстановки шифротекста → 3 теста падают
 - **Статус:** ✅ Исправлено в specs/009


### #54 — Дефолт доступа к состояниям автоматов был «на отказ»: запрос без прав видел всё · Low
*(выявлено 2026-10-05 при работе по очереди 5 продакшен-плана, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/routes/__init__.py` (`_resolve_accessible_device_ids`, `get_fsm_state`, маршрут дашборда), `src/webui/templates/dashboard.html`, `tests/contract/test_fsm_state_access_default.py` (новый, 7)
 - **Ошибка 1 — три ветки выдавали полный доступ.** Функция возвращала `None` («без фильтрации») если заголовок `X-User-ID` отсутствует, если сервис устройств недоступен и если фильтрация упала с исключением. Все три означали «видно всё». Самое существенное — первое: **запрос без единого заголовка получал состояния всех устройств**
 - **Ошибка 2 — сбой расширял права.** Исключение при фильтрации превращалось в разрешение: отказ хранилища был неотличим от успеха, и данные отдавались именно тогда, когда права проверить не удалось. Сломанный сервис устройств выдавал больше, чем исправный
 - **Ошибка 3 — дашборд зависел от этого дефекта.** `dashboard.html` был единственным шаблоном без `data-user-id` на `<body>`, его `authHeaders()` возвращал `{}`, а маршрут не передавал `user_id` / `user_is_admin` в контекст. Поэтому исправить сервер «в одну строку» было нельзя: дашборд сломался бы, получая отказ вместо данных
 - **Тест закреплял дефект как норму.** `test_should_work_without_identity_header` в `tests/contract/test_fsm_live_contract.py` утверждал 200; его докстринг при этом обещал «показываются только доступные», то есть прямо противоположное проверяемому. Заменён на требование 401
 - **Что сделано:** дефолт стал отказом — нет `X-User-ID` → 401; сервис устройств недоступен → 503; фильтрация упала → 503 с причиной в журнале. Дашборд получил `data-user-id` / `data-user-is-admin` и настоящие `authHeaders()`; маршрут передаёт идентичность в контекст так же, как `index.html`
 - **Проверено запуском контейнера:** дашборд отдаёт `data-user-id="admin_user"` и `data-user-is-admin="true"`; запрос без заголовков → 401 `Missing X-User-ID header`; запрос администратора → 8 устройств
 - **Чувствительность:** возврат `return None` при отсутствии заголовка → 3 теста падают; возврат пустых `authHeaders()` → падает тест на заголовки дашборда
 - **Честное ограничение:** заголовки подделываются одним значением, поэтому защита отсекает клиентов, которые не знают про заголовки, но не от намеренного атакующего. Полноценная защита — отдельная фича (пункт 4 плана) либо сетевой уровень
 - **Статус:** ✅ Исправлено в specs/009


### #55 — Шесть эндпоинтов источников и POST /apply не проверяли права вовсе · Low
*(выявлено 2026-10-05 при работе по очереди 5 продакшен-плана, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/routes/devices/sources.py`, `src/webui/routes/devices/devices.py`, `tests/contract/test_source_endpoints_require_admin.py` (новый, 20), `tests/contract/test_apply_requires_admin.py` (новый, 4)
 - **Состояние до правки:** `require_admin` существовал в проекте, но применялся только к управлению доступом. Ни один эндпоинт `/api/v1/devices/sources` не проверял права — ни администратора, ни наличия идентичности. `POST /api/v1/devices/apply`, который создаёт машины состояний, строит карту маршрутизации и меняет манифест, при этом обещал в докстринге 403, но проверок не содержал
 - **Доказано:** обычный пользователь получал **201 Created** на `POST /apply`, то есть операция, меняющая конфигурацию платформы, выполнялась. На списке источников — 200 с данными
 - **Ошибка 2 — аудит записывал несуществующего пользователя.** `_current_user_id` возвращал строку `"system"`, когда идентичности в запросе нет. Операция выполнялась от имени «system», и в журнале не оставалось следа, кто её инициировал
 - **Ошибка 3 — две подготовки в тестах проходили только благодаря дефекту.** `tests/contract/test_access_control.py::sample_source` и `tests/integration/test_device_sync.py::test_sync_requires_identity` создавали источник без заголовков. Оба теста проверяли не то, о чём заявляли: первый готовил данные для проверки прав, второй проверял отказ синхронизации без идентичности, а оба падали бы на отказе 403 при подготовке
 - **Что сделано:** `require_admin` подключён к шести эндпоинтам источников (список, создание, чтение, удаление, синхронизация, данные обнаружения) и к `POST /apply`. Обе подготовки в тестах переведены на создание источника от имени администратора — точечно, а не через фикстуру клиента: та используется и для проверок прав, и `X-Is-Admin: true` по умолчанию сделал бы «stranger» администратором
 - **Интерфейс не сломан:** `discovery.html` перехватывает `window.fetch` и добавляет идентичность ко всем `/api/`; дефолт `WEBUI_DEFAULT_USER_ADMIN` = `true`, поэтому интерфейс по умолчанию работает как администратор
 - **Проверено запуском контейнера:** без прав `/api/v1/devices/sources` → 403 `Admin access required`; `/api/v1/devices/apply` → 403; с правами администратора список источников → 200; `/dashboard` и `/` → 200
 - **Чувствительность:** снятие `require_admin` с шести эндпоинтов → 7 тестов падают; снятие с `/apply` → падает тест на права
 - **Статус:** ✅ Исправлено в specs/009


### #56 — Сторож не работал ни разу: падал каждый цикл на неверном имени атрибута адаптера · Low
*(выявлено 2026-10-05 проверкой готовности `/ready`, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/services/watchdog.py` (`AdapterProtocol`, `_with_connection`), `tests/unit/services/test_watchdog.py`
 - **Симптом в контейнере:** `Watchdog check failed unexpectedly: AttributeError: 'HAAdapter' object has no attribute 'connected'` — повторялся каждый цикл. Снимков сторожа не было ни одного: в логах 0 строк `[WATCHDOG]`
 - **Причина:** `AdapterProtocol` объявлял свойство `connected`, которого нет ни у `HAAdapter`, ни у `MockAdapter` — у обоих `is_connected`. `src/services/watchdog.py:509` был **единственным** местом в проекте, читавшим `adapter.connected`
 - **Почему исключение не было заметно:** цикл сторожа ловит исключение и продолжает работу, записывая предупреждение. Платформа выглядела исправной, но обнаружение зависших автоматов и потери связи с HA **не работало никогда**
 - **Почему тесты это не видели:** проверки потери связи использовали `MagicMock` и присваивали `adapter.connected`. `MagicMock` создаёт любой атрибут по требованию, поэтому проверка имени проходила, хотя ни одна реальная реализация такого имени не имеет. Это третий случай подряд, когда `MagicMock` скрывал расхождение интерфейсов (см. #30)
 - **Что сделано:** `AdapterProtocol` объявляет `is_connected`, `_with_connection` читает `is_connected`. Четыре теста переведены с `MagicMock` на строгий фейк `StrictAdapter`, у которого лишних атрибутов нет; добавлен тест `test_should_work_with_adapter_exposing_only_is_connected`, который проверяет сторож с адаптером ровно того вида, что есть в проекте
 - **Проверено запуском контейнера:** снимки сторожа публикуются каждые 60 с (`fsm_count: 8`, `ha_checked: true`), число `AttributeError` — 0
 - **Статус:** ✅ Исправлено в specs/009


### #57 — `/health` отвечает константой; проверки готовности не было · Low
*(выявлено 2026-10-04 аудитом как K6, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/routes/readiness.py` (новый), `src/webui/routes/__init__.py` (`check_readiness`), `src/services/watchdog.py` (`_last_snapshot`), `tests/contract/test_readiness_endpoint.py` (новый, 15), `tests/unit/webui/test_readiness_checks.py` (новый, 13)
 - **Было:** `GET /health` возвращал `{"status": "ok"}` безусловно. Docker считал контейнер здоровым при мёртвом Home Assistant и нечитаемом каталоге данных
 - **Почему `/health` не тронут:** контракт спеки 003 (`contracts/operational-contracts.md` §1) прямо требует не отдавать не-200 как «not ready». Практически это верно: если начать отдавать 503 при недоступном HA, healthcheck убьёт контейнер, перезапустит, тот снова увидит недоступный HA — рестарт-цикл, в котором перезапуск ничего не исправляет
 - **Что сделано:** добавлен `GET /ready` с пятью проверками — каталог данных (реальная запись во временный файл с удалением), файл ключа шифрования, связь с HA, свежесть снимков сторожа, состояние движка автоматов. Каждая проверка выполняется независимо, чтобы в ответе были видны все причины. Код 503 при отказе. Docker healthcheck по-прежнему ходит в `/health`
 - **Побочный дефект, найденный при реализации:** сторож не сохранял последний снимок, поэтому «сторож молчит» и «сторож не работает» были неразличимы. Добавлено поле `_last_snapshot`, заполняемое в обоих путях `check_once` — успешном и при сбое
 - **Ошибка в моей реализации, найденная тестами:** метка времени снимка — наивное время **UTC** (`_now_timestamp()` делает `datetime.now(UTC).replace(tzinfo=None)`), а я разбирал её как местную. В контейнере с не-UTC-смещением возраст снимка выходил на 18000 с вместо 22 с, и свежий снимок объявлялся устаревшим. Тесты на это повалились
 - **Именование:** обработчик назван `check_readiness`, а не `readiness`: одноимённая функция перекрыла подмодуль `webui.routes.readiness`, и `from webui.routes import readiness` отдавал функцию вместо модуля — проверки нельзя было вызывать напрямую из тестов
 - **Ошибка в моём тесте:** тест снимал `DATA_PATH` и вызывал проверку, которая по назначению создаёт относительный каталог `data` — и засорял корень репозитория. Добавлен `monkeypatch.chdir(tmp_path)`
 - **Проверено запуском контейнера:** `/ready` сначала честно отдал 503 с `watchdog: сторож ещё не опубликовал ни одного снимка`, а после починки сторожа — 200 со всеми пятью проверками (`watchdog: возраст=22.0с зависаний=0`). `/health` отдаёт ровно `{"status": "ok"}` и 200
 - **Чувствительность:** подмена проверки каталога на «всегда хорошо» → 3 теста падают; игнорирование возраста снимка → падает тест на устаревший снимок; чтение наивного времени как местного → 2 теста падают; возврат чтения `adapter.connected` → 4 теста падают
 - **Польза сверх плана:** проверка готовности вскрыла дефект #56, который был невидиден месяцами
 - **Статус:** ✅ Исправлено в specs/009


### #58 — Резервная копия была на том же хосте и не имела проверки целостности; путь развёртывания был зашит в скрипт · Low
*(выявлено 2026-10-05 при работе по очереди 6 продакшен-плана, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `deploy/scripts/deploy.sh`, `tests/contract/test_deploy_backup.py` (новый, 17)
 - **Что требовал план (Блокер 3-бис):** регулярный `tar`/`zstd` тома `data/` + `manifest.yaml` во внешнее хранилище с проверкой целостности и тестом восстановления
 - **Ошибка 1 — копия не имела ни сжатия, ни проверки, ни восстановления.** `create_backup` делала `cp -r` в `backups/backup_<дата>` на том же хосте. Проверки целостности не существовало: единственный способ узнать о повреждении копии — обнаружить его при попытке восстановления. Команды `verify` и `restore` не было вовсе, `rollback` восстанавливал из каталога, который никто не проверял
 - **Ошибка 2 — не было ротации.** Число копий росло неограниченно, то есть бэкапы сами становились причиной нехватки места
 - **Ошибка 3 — `DOCKER_COMPOSE_FILE` был зашит литералом.** Скрипт нельзя было направить ни в другое окружение, ни в изолированный каталог. Это нашлось неприятным образом: **тесты с песочницей проходили, а `restore` раскладывал данные по настоящим каталогам `deploy/docker/`**. Каталоги уцелели только потому, что копия снималась с того же места, откуда раскладывалась. Путь задаётся переменной окружения, и это не удобство, а условие безопасности
 - **Что сделано:** `backup` собирает `tar.gz` из `config/` и `data/`, считает SHA256 **внутри архива** и сразу проверяет результат — нечитаемая копия удаляется вместо того, чтобы остаться видимой защитой. Добавлены `verify` и `restore`. `restore` проверяет копию **до** остановки сервиса и до затирания, сохраняет текущее состояние в `pre_restore_*`, отменяется на битой копии. Ротация через `BACKUP_KEEP` (по умолчанию 7). Назначение — `BACKUP_DEST_DIR`; по умолчанию тот же хост, и скрипт **предупреждает**, что это не защита от потери диска
 - **Ошибки macOS в моей реализации, найденные тестами:** `tar -C staging .` давал имена с префиксом `./`, и проверка содержимого копии снаружи их не находила; `cp -r` переносил расширенные атрибуты как файлы `._*` — мусор в архиве, который раздувает копию и ломает проверку при переносе на Linux. Члены архива перечисляются явно, добавлен `COPYFILE_DISABLE=1`
 - **Моя слабая проверка, усиленная после инъекции:** отказ `restore` на обрезанном архиве ловится самой распаковкой, то есть проходил бы даже с отключённой сверкой сумм — инъекция это подтвердила (16 тестов зелёные). Добавлена подделка содержимого при живом архиве: копия открывается, но суммы не сходятся. Только она различает «отказ по проверке» и «сбой при распаковке»
 - **Проверено:** `deploy/docker/config/manifest.yaml` сохранил хеш `d5c0f6be4fd71928` во время всех прогонов; тест сравнивает содержимое боевых каталогов до и после, и отдельная проверка требует, чтобы путь к compose-файлу читался из окружения
 - **Чувствительность:** возврат зашитого пути к compose-файлу → 6 тестов падают; отключение сверки сумм перед восстановлением → падает тест на подделанный архив; отключение ротации → 15 тестов падают
 - **Статус:** ✅ Исправлено в specs/009 (проверяемая часть)


### #59 — Копия создаётся на том же хосте, что и данные · Low
*(выявлено 2026-10-04 аудитом как Блокер 3-бис, частично 2026-10-05, спека 009)*
 - **Остаток:** `deploy.sh backup` создаёт сжатую проверенную копию, но по умолчанию кладёт её рядом с данными. От потери диска или хоста это не защищает
 - **Что сделано:** назначение вынесено в `BACKUP_DEST_DIR`, по умолчанию — тот же хост с явным предупреждением, что это не защита. В `deploy/README.md` добавлены пример настройки сетевого каталога и cron хоста
 - **Чего нельзя проверить здесь:** выгрузку во внешнее хранилище нельзя доказать без инфраструктуры — сетевого каталога, бакета или внешнего диска. Проверяемая часть (сжатие, суммы, проверка, восстановление, ротация, файл ключа) сделана и покрыта тестами; выбор хранилища — решение владельца
 - **Статус:** ◐ Требует решения владельца: куда складывать копии


### #60 — `BackupService` выглядит как защита, которой нет · Low
*(выявлено 2026-10-04 аудитом, спека 009)*
 - **Факты:** класс полностью реализован, но вызывается **только в своих тестах** — `grep -rn "BackupService" src/` находит единственное упоминание в самом файле. Бэкапит он не платформу, а Home Assistant: `get_automations`, `get_scripts`, `get_scenes`, плюс `restore_backup`
 - **Почему это плохо:** класс называется `BackupService` и лежит в `src/services/`, то есть выглядит как резервное копирование платформы. Читатель кода примет его за защиту данных, которой нет
 - **Что нужно решить (владелец):** (а) удалить как мёртвый код; (б) включить в контур — например, вызывать `create_backup` перед рискованными операциями; (в) оставить, но переименовать и пометить как утилиту экспорта HA. Самовольное удаление работающего кода — не моё решение
 - **Статус:** Не исправлено (требует решения владельца)


### #61 — Guard'ы и действия шаблоны требовали, но в коде их не было — переходы не выполнялись · Low
*(выявлено 2026-10-05 при планировании работы над интерфейсом, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/core/guards/builtin.py` (новый), `src/core/action_handlers.py`, `src/core/container.py`, `tests/unit/core/test_builtin_guards_actions.py` (новый, 31)
 - **Симптом:** при каждом старте логи содержали `Guard 'is_day_time' not found in registry` и `Action 'climate_heat' not found in registry`. Движок при отсутствии обработчика **отклоняет переход** (`FSMEngine._evaluate_guard`), то есть платформа выглядела исправной, но не переключала ничего
 - **Масштаб по сверке `src/features/*.yaml` с реестром:** guard'ов зарегистрирован **ноль** при четырёх требуемых (`is_day_time`, `is_manual_override_enabled`, `humidity_above_60`, `humidity_below_60`); действий зарегистрировано **5** при десяти требуемых манифестом
 - **Дополнительно найдено при сверке:** `registry` в `container.py` регистрировал только действия — guard'ы не регистрировал **никто**
 - **Что сделано (вариант (а) — то, что требует текущий манифест):** четыре встроенных guard'а и пять действий (`climate_heat`, `climate_cool`, `climate_off`, `fan_turn_on`, `fan_turn_off`). Guard'ы строятся фабриками, потому что им нужны сервисы — трекер ручного вмешательства и диапазон дня; реестр хранит только функции, обычная функция их получить не смогла бы
 - **Принцип отказа при нехватке данных:** нет значения датчика или идентификатора устройства — переход запрещается. Разрешить автоматику вслепую хуже, чем не включить свет; при отсутствующем датчике включение вентиляции выглядело бы как ложное срабатывание
 - **Порог влажности берётся из параметров поведения** (`humidity_threshold`, в манифесте 65), а не из имени guard'а (`humidity_above_60`). Иначе настройка в интерфейсе молча не влияла бы на поведение. Значение 60 используется как запасное
 - **Диапазон дня** `07:00-23:00`, дополняет ночное расписание `23:00-07:00` из манифеста; переопределяется `DAY_TIME_RANGE`. Некорректный диапазон **запрещает** переход: «непонятный день» не должен разрешать включать свет ночью
 - **Проверка проводки, добавленная после инъекции:** первая версия теста смотрела только на наличие функций в модуле, и отключение регистрации проходило незамеченным — 27 тестов зелёные при полностью отключённых guard'ах. Добавлены проверки реестра контейнера: все guard'ы из **всех** шаблонов `src/features/` должны быть зарегистрированы
 - **Проверено запуском контейнера:** `Registered 10 action handlers`, все 4 guard'а в реестре, `is_day_time` возвращает `True` днём; число «not found in registry» — **0** (было 80+ за запуск); `/ready` — 200 со всеми пятью проверками, `home_assistant: соединение установлено`; сторож публикует `result: ok`
 - **Наблюдение:** строка `Registered 4 guards` в логах контейнера не появляется, хотя регистрация происходит — вероятно, регистратор из `core.guards.builtin` не подключён к обработчику loguru. На работу не влияет, но для диагностики стоит привести к общему виду
 - **Осталось вне варианта (а):** ещё 18 действий для шаблонов замков, штор и скоростей (`confirm_lock`, `start_opening`, `set_high_speed` и другие). Ими этот дом не пользуется
 - **Статус:** ✅ Исправлено в specs/009


### #62 — Источники нельзя было удалить из интерфейса, а статус не показывался · Low
*(выявлено 2026-10-05 при работе над пунктом 1 веб-плана, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/templates/discovery.html`, `tests/contract/test_source_management_ui.py` (новый, 16)
 - **Уточнение к прежней оценке:** создание источника **было** реализовано — форма `source-form` с полями и разбором 422 по полям через `showSourceFormErrors`. Мой прежний вывод «интерфейса нет» был неверен: поиск по именам функций (`createSource`, `addSource`) не нашёл форму, отданную сервером с `id="source-form"`. Ошибка в том, как я искал, а не в коде
 - **Ошибка 1 — удаления не было вовсе.** Ноль вхождений удаления в шаблоне; карточка источника — `<div>` без кнопок. Ошибочно созданный источник невозможно было убрать
 - **Ошибка 2 — статус не отображался.** `SourceResponse` отдаёт `status`, `last_sync`, `last_error`, но карточка выводила только название и адрес. Отключённый источник с ошибкой выглядел ровно как рабочий, и именно эта ошибка объясняет, почему устройства не добавляются
 - **Что сделано:** кнопки «Синхронизировать» и «Удалить» на карточке, бейдж статуса, время последней синхронизации, текст `last_error`. Удаление спрашивает подтверждение, в котором названо **что именно** удаляется и что вместе с источником отвязываются устройства; отказ от подтверждения ничего не отправляет; после успеха список перечитывается
 - **Кнопки внутри карточки не выбирают источник:** без этого удаление сначала переключило бы страницу на удаляемый источник
 - **Проверено запуском контейнера:** источник создан, синхронизация дала отказ и заполнила `last_error` («Не удалось подключиться к HA») — то есть данные, которые теперь видит пользователь, действительно появляются; `DELETE` вернул 204, источник исчез из списка; новая логика присутствует в отданной странице
 - **Две ошибки в моих тестах, найденные прогонами:** регулярка `confirm\((.{0,400})\)` обрывалась на первой скобке и не видела собранное заранее название источника; `split("deleteSource", 1)[-1]` брал первое вхождение имени — это wires обработчика, а не определение функции, и проверялся не тот код. Оба заменены на вырезание тела функции
 - **Чувствительность:** снятие `window.confirm` → 4 теста падают; снятие перечитывания списка после удаления → 1 тест падает; снятие показа `last_error` и `last_sync` → 2 теста падают
 - **Статус:** ✅ Исправлено в specs/009


### #63 — Фактическое состояние устройства не отображалось нигде · Low
*(выявлено 2026-10-05 при работе над пунктом 2 веб-плана, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/templates/index.html`, `tests/contract/test_device_state_display.py` (новый, 12)
 - **Уточнение к прежней оценке:** состояние **автомата** на карточке уже выводилось — функция `renderDeviceStates` в `index.html` (FR-028). Мой прежний вывод «состояние не выводится» был неверен: я искал обращение к `device.state` и не нашёл, хотя состояние автомата приходит из другого источника
 - **Чего действительно не было:** состояния самого устройства и его доступности. `/api/fsm/state` отдаёт только состояние автомата (`OFF`, `ON_MOTION`, `IDLE`) — то есть как ведёт себя автоматика. Состояние устройства (`on`/`off`) лежит в `/api/v1/devices` в поле `state`, и в интерфейсе не отображалось нигде
 - **Почему различие существенно:** «автоматика в режиме ON_MOTION» ничего не говорит о том, горит ли лампа. Молчащий интерфейс выглядит как «работает штатно», даже когда устройство недоступно
 - **Что сделано:** бейдж состояния устройства рядом с состояниями автоматов, плюс отдельный бейдж недоступности при `status != available`. Неизвестные значения показываются как есть, а не исчезают: у Home Assistant десятки состояний
 - **Лишний запрос устранён:** `/api/v1/devices` уже запрашивался в `loadInitialData`, но результат не использовался. Отдельный запрос не добавлен, состояние берётся из уже загруженных данных
 - **Экранирование объявлено отдельно:** `escapeHtml` в `index.html` не существовало — функция есть только в `discovery.html`. Подстановка через `innerHTML` значения из Home Assistant без экранирования небезопасна
 - **Три ошибки в моих проверках, найденные инъекциями.** Первая версия искала строки в файле: инъекции «убрать вызов `renderDeviceState`» и «убрать вызов `renderDeviceStates`» прошли при 7 зелёных тестах. Добавлены проверки тел функций. Затем инъекция «снять экранирование у названия состояния» прошла, потому что `escapeHtml` в теле функции есть и для статуса — проверка уточнена до конкретной подстановки
 - **Чувствительность:** снятие вызова `renderDeviceState` → падает проверка отрисовки устройства; снятие наполнения в `loadInitialData` → падает проверка начальной загрузки; снятие экранирования названия → падает проверка экранирования
 - **Проверено:** страница отдаёт новую логику (10 совпадений в разметке), контракт `/api/v1/devices` и `/api/fsm/state` покрыт тестами
 - **Чего проверить не удалось:** видимый бейдж требует хотя бы одного синхронизированного устройства, а список устройств пуст — это пункт 5
 - **Побочная находка:** источник `Shilovo` в развёртывании указывает на `http://homeassistant.local:8123/`, и это имя **не резолвится из контейнера** — синхронизация падает с «Не удалось подключиться к HA». Адрес источника не связан с `HA_URL` из окружения и был задан вручную
 - **Статус:** ✅ Исправлено в specs/009 (код и контракт); видимая проверка требует пункта 5


### #64 — Пользователь вводил вручную то, что уже задано в окружении; при этом источник оказался с нерезолвящимся адресом · Low
*(выявлено 2026-10-05 при замене источника, исправлено 2026-10-05, спека 009)*
 - **Файлы:** `src/webui/routes/devices/sources.py`, `src/webui/templates/discovery.html`, `tests/contract/test_source_from_env.py` (новый, 14)
 - **Просьба владельца:** «при отсутствии источника есть смысл подставлять значения из `.env` и какое-нибудь default имя»
 - **Почему это важно:** платформа уже подключается к HA по `HA_URL` и `HA_TOKEN` из окружения (`core/container.py:195`). Пользователю приходилось вводить в форму ровно то, что уже задано, и он неизбежно ошибался. Это проявилось буквально: в развёртывании жил источник с адресом `homeassistant.local:8123/`, который из контейнера **не резолвится** — синхронизация падала, тогда как `HA_URL` в `.env` был верным
 - **Главное требование — токен не должен покидать сервер.** Поэтому два разных вызова: `GET /from-env` отдаёт только несекретное (имя, адрес, признак наличия токена), а `POST /from-env` создаёт источник на сервере и в ответе токен не возвращает. Наивный вариант «отдать токен, чтобы предзаполнить поле» оставил бы секрет в HTML и в истории браузера
 - **Имя по умолчанию** «Home Assistant» — его видит пользователь в списке, поэтому «Источник 1» хуже
 - **Что сделано:** подсказка показывается, только когда источников нет; поля имени и адреса предзаполняются; создание идёт одной кнопкой; обе операции требуют прав администратора
 - **Ошибка типов, найденная mypy, и связанная с ней:** `HASource.url` имеет тип `HttpUrl`, и `str` из окружения передавался напрямую. Проверка добавлена явно через `TypeAdapter(HttpUrl)` — иначе неверный `HA_URL` дал бы 500 с текстом валидатора pydantic вместо отказа 409 с указанием на `HA_URL`
 - **Первая инъекция на утечку токена не сработала:** добавление `token=token` в вызов модели молча отбрасывалось — `SourceFromEnvResponse` не имеет такого поля, а лишние аргументы pydantic игнорирует. Настоящая утечка (добавление поля в саму модель) поймана сразу
 - **Ошибка в моём тесте:** заголовок `X-User-ID` со значением на кириллице вызвал `UnicodeEncodeError` в тестовом клиенте. Заменено на ASCII
 - **Проверено запуском контейнера:** подсказка отдаёт `{"available":true,"has_token":true,"url":"http://192.168.2.10:8123","name":"Home Assistant"}`; поиск токена в ответе — 0 совпадений; `POST` без прав — 403 `Admin access required`
 - **Синхронизация после замены источника:** 1490 устройств из реального Home Assistant
 - **Наблюдение:** 1490 устройств — интерфейсу предстоит отрисовать их все. Страница уже тянет `/api/v1/devices` целиком; на таком объёме это заметная нагрузка на браузер и сеть. Отдельная задача по постраничности или фильтрации
 - **Статус:** ✅ Исправлено в specs/009


### #65 — Устройство, добавленное или удалённое через веб-интерфейс, не сохранялось — терялось при перезапуске · Low
*(выявлено 2026-10-05 при сквозной проверке пункта 5 веб-плана, исправлено 2026-10-05, спека 009)*
- **Файлы:** `src/services/device_lifecycle.py` (`add_device`, `_upsert_manifest_entry`), `src/webui/routes/devices/devices.py` (`POST /api/v1/devices/apply`)
- **Класс:** потеря данных. Регресс, внесённый F1
- **Суть:** `DeviceLifecycleService.add_device()` правит манифест в памяти (`_upsert_manifest_entry`) и на этом заканчивает. Ссылок на `manifest_store` в модуле — **0**, вызовов `.save()` — **0**. Старый путь `discovery_service.apply_selective` сохраняет (`store.save()`, строки 258 и 436), новый путь F1 — нет. Итог: два разных пути для одной операции, один из них молча теряет запись
- **Доказательство запуском:** `POST /api/v1/devices/apply` с реальным устройством → HTTP 201, `success: true`; `devices_added: 0`, `devices_updated: 1`. В контейнере проверены обе копии манифеста — `/config/behavioral_platform/manifest.yaml` (3024 Б) и `/app/instances/leonids_house/manifest.yaml` (2667 Б) — устройства нет ни в одной (`grep -c` → 0)
- **Смежный дефект отчётности в том же маршруте:** `added`/`updated` считаются по `existing is not None` в синхронизированном хранилище, где устройство уже есть среди 1490 записей. Поэтому ответ рапортует об «обновлении», хотя запись манифеста не создана вовсе. Число `devices_added: 0` при `success: true` — это не «нечего добавлять», а «добавление не сохранилось»
- **Кто чинит:** `device_lifecycle.py` не имеет доступа к `ManifestStore`. В `app.py:356` хранилище отдаётся только в `init_discovery_routes`, поэтому передача хранилища в контейнер сервисов — часть решения
- **Расширение при разборе:** дефект оказался не в добавлении, а в классе — манифест трогают три метода, и не сохраняет ни один. `add_device` (строка 130), `update_device` (182), `delete_device` (404). То есть **удаление** устройства через интерфейс тоже выглядело выполненным, а устройство возвращалось после перезапуска
- **Ловушка, потребовавшая обхода:** приложение держит **две копии манифеста**. `Container.manifest` грузится через `load_manifest()`, `ManifestStore` разбирает тот же файл собственным `load()` — это разные объекты (проверено в контейнере: `a is b` → `False`, разные `id()`). Починка вида «передать хранилище и вызвать `save()`` записала бы устаревший снимок, то есть молча ничего бы не сохранила. `_save_manifest()` перенаправляет хранилище на живой объект перед записью
- **Попутно найдено:** `yaml.dump` без `allow_unicode` записывал русские имена как `\u041F\u0440...` — валидный YAML, который не прочитать глазами. Валидатор и загрузчик такие последовательности понимают, поэтому дефект был не виден ни одному из них
- **Побочный эффект, потребовавший изоляции тестов:** два контрактных файла (`test_devices_api.py`, `test_fsm_live_contract.py`) брали синглтон `main.app`, собранный на манифесте репозитория, и с сохранением манифеста их правки устройств попадали в `instances/leonids_house/manifest.yaml`, ломая `tests/test_bootstrap.py` (9 устройств вместо 6, имя `Get By Id Success` от теста). До починки правки не доходили до файла, поэтому и не мешали
- **Что сделано:** `manifest_store` передан в `DeviceLifecycleService`; `_save_manifest()` вызывается в `add_device` (с откатом комнаты при сбое), `update_device` и `delete_device`; `allow_unicode=True` в обоих дампах `ManifestStore`; сквозные тесты переведены на изолированное приложение
- **Тесты:** 7 юнит-тестов на живом `ManifestStore` в `tmp_path` + 2 сквозных контрактных через `POST /api/v1/devices/apply`. Утверждения читают **файл на диске**, а не заглушку
- **Чувствительность проверена инъекциями** (восстановление по sha256): без перенаправления `current` краснеют 4 теста; с выключенным `save()` в любом из трёх мутаторов краснеет соответствующий тест; с убранной проводкой из `app.py` краснеют 2 сквозных и **остаются зелёными 7 юнит-тестов** — сквозные проверяют проводку, которой юниты не видят
- **Проверено запуском контейнера:** `apply` → устройство в файле манифеста и на хосте, и в контейнере → перезапуск → FSM выжила → включение датчика → `OFF → ON_MOTION`, лампа загорелась. Удаление → перезапуск → устройства нет. Полный прогон 2252 passed / 0 failed
- **Статус:** ✅ Исправлено в specs/009 (2026-10-05), коммит `53778dc`


### #66 — Таймаутные переходы FSM не срабатывали — таймер взводился не по тому переходу · Low
*(выявлено 2026-10-05 при сквозной проверке пункта 5 веб-плана, исправлено 2026-10-05, спека 009)*
- **Файлы:** `src/core/fsm/engine.py` (взвод таймера в `trigger`), `src/features/lighting.yaml:57-61`
- **Суть:** движок взводил таймер по `timeout_sec` **сработавшего** перехода. Шаблоны объявляют `timeout_sec` на **исходящем**: в `lighting.yaml` это `ON_MOTION --[timeout]--> OFF, 30.0`, а переход `OFF --[motion_detected]--> ON_MOTION` таймера не несёт. Переход в `ON_MOTION` проходил без таймера, состояние жило вечно. `expected_timeout_sec` при этом возвращал 30.0 — он читает исходящие переходы, — то есть сторож видел ожидание, которого движок не выполнял
- **Почему дефект не был виден в тестах:** движок проверяли описания в форме «таймер на входящем переходе» (`OFF --[motion_detected]--> ON_AUTO, timeout_sec=300`) — именно эту форму использовали существующие тесты. Шаблоны написаны в другой
- **Доказательство запуском до починки:** состояние `ON_MOTION` удерживалось 90+ с, лампа не гаснет; сторож отработал корректно и зафиксировал сам — `expected_timeout_sec: 30.0`, `stuck: true`, `result: degraded`. Детектор был исправен, исполнитель — нет
- **Что сделано:** взвод по исходящим переходам нового состояния с фильтром по триггеру `timeout`. Фильтр обязателен: иначе таймер встал бы в состоянии, где событие `timeout` никем не обрабатывается (форма `OFF --[manual_override]--> ON_MANUAL, timeout_sec=3600` в `generic_switch.yaml`)
- **Отдельный отменяющий таймер не понадобился:** `trigger` уже снимает все таймеры автомата в начале обработки (`engine.py:635`). Метод `_cancel_timer` был введён, оказался мёртвым и удалён — иначе в коде остался бы второй, никем не используемый путь отмены
- **Одно существующее утверждение обновлено:** `test_should_not_change_transition_behaviour_when_reading` проверял, что таймер не взводится при входе в состояние с таймером — верно для прежнего движка, ложно для исправленного. **Расхождение `expected_timeout_sec` с движком на форме «таймер на исходящем переходе с другим триггером» оставлено как есть** и отмечено в тесте отдельной задачей: чтение сторожа считает все исходящие переходы, взвод — только по триггеру `timeout`
- **Тесты:** 7 новых в `tests/unit/core/test_fsm_timeout_scheduling.py`. Чувствительность проверена инъекцией с восстановлением по sha256: с возвратом взвода по сработавшему переходу краснеют 4 теста
- **Проверено запуском контейнера на реальном устройстве:** переход `OFF → ON_MOTION` по `input_boolean.shp_smoke_test_motion`, затем **ровно через 30 с** (`16:45:50 → 16:46:20`) состояние ушло в `OFF`, лампа погасла. До починки горела неограниченно долго
- **Ошибка в моей проверке:** таймаут в 8 с я хотел задать полем `behavior_params`, но такого поля у `DeviceSelection` нет — pydantic молча отбросил его, и параметр не применился. Проверка отработала на штатных 30 с шаблона, что даже надёжнее. Правильная форма — `behaviors: [{template, priority, params}]`
- **Статус:** ✅ Исправлено в specs/009 (2026-10-05), коммит `02a8cb6`


### #67 — Контракт платформы и шаблонов поведения расходится: события приходят в никуда, триггеры — из ниоткуда · Low
*(выявлено 2026-10-05 при сквозной проверке пункта 5 веб-плана, частично закрыто 2026-10-05, спека 009)*
- **Файлы:** `src/features/CONTRACT.yaml` (новый, генерируется), `tools/gen_template_contract.py` (новый), `tests/contract/test_template_contract.py` (новый, 18), `src/core/events/event_router.py` (`SENSOR_EVENT_MAP`), `src/features/*.yaml`
- **Исходный симптом:** при выключении датчика роутер отдаёт `event=motion_cleared` (журнал: `Routing: sensor=input_boolean.shp_smoke_test_motion → fsm=…_lighting_10, event=motion_cleared`), но в шаблоне `lighting` перехода по этому триггеру нет — реакция реализована только через `timeout`
- **Картина оказалась общей, а не частной.** `EventRouter` публикует **7** событий, и из них шаблоны слушают **одно** — `motion_detected`. Не покрыты `motion_cleared`, `temperature_changed`, `humidity_changed`, `brightness_changed`, `opened`, `closed`. В обратную сторону: **27 из 28** триггеров шаблонов не порождаются ничем; часть приходит из движка (`timeout`), остальные не имеют источника вовсе — `manual_switch_on`/`manual_switch_off`, `manual_override`, `schedule_end`, `temperature_low`/`high`/`reached`, `humidity_high`/`normal`, `open`/`close`/`stop`, `lock`/`unlock`, скорости
- **Часть расхождений — просто разные имена:** роутер публикует `humidity_changed`, шаблон слушает `humidity_high`/`humidity_normal`; роутер публикует `temperature_changed`, шаблон слушает `temperature_low`/`high`/`reached`
- **Почему шаблоны не переименованы:** переименование не чинит. У `climate_control` guard'ов **нет вовсе**, и у переходов нет порогов — при исправленных именах любое изменение температуры включало бы обогрев, а возврат к норме выключал бы. Это решение о семантике поведения, а не правка дефекта; по FR-026 не делается молча
- **Что сделано:** контракт вынесен в `src/features/CONTRACT.yaml` и **генерируется из кода**. Правка шаблона, реестра или карты событий без перегенерации роняет тест — документ не может разойтись с кодом тихо
- **Чувствительность проверена инъекциями** (восстановление по sha256): переход, добавленный в шаблон, роняет 1 тест; удаление события из `SENSOR_EVENT_MAP` — 2; удаление действия `fan_turn_on` из реестра — 3
- **Тест не требует, чтобы каждый триггер имел источник:** таких пробелов 26, и требование сделало бы набор красным навсегда. Вместо этого они перечислены машинно-читаемым полем `unproduced_triggers` и описаны прозой в `gaps`. Первая редакция теста требовала, чтобы проза упоминала каждый триггер поимённо, — заменена: текст всё равно читать глазами, а машина его не проверяет
- **Значение для веб-плана:** это и есть тот самый «контракт шаблонов» для пунктов 3 и 4. По таблице форма поведения строится из того, что платформа правда выполнит
- **Осталось незакрытым (отдельными задачами):** согласование имён событий для `climate_control` и `humidity_ventilation` вместе с порогами как параметрами поведения; решение по `motion_cleared` в `lighting` (выключать сразу или с удержанием); отсутствие guard'а «ночь» у `night_light`; ручной путь `manual_*` как класс (пункт 3 веб-плана); 18 незарегистрированных действий для штор, замков и скоростей (вне варианта (a))
- **Статус:** 🟡 Частично закрыто — контракт задокументирован и защищён от расхождения, сами пробелы не устранены


### #68 — `GET /manifest/reload` не перечитывал манифест в работающей платформе · Low
*(выявлено 2026-10-05 при закрытии K7, исправлено 2026-10-05, спека 009)*
- **Файлы:** `src/webui/app.py:543` (маршрут), `src/core/persistence/manifest_store.py` (`reload_into`), `tests/contract/test_manifest_reload.py` (новый, 13)
- **Дефект 1 — отказ без посещения главной.** `manifest_store.load()` вызывался только внутри обработчика `GET /`, а не при старте. Проверено парой запросов: reload → **400** `No manifest loaded`; после `GET /` тот же запрос → **307**
- **Дефект 2 — успешный отклик без результата.** `revert()` делал `self.current = copy.deepcopy(self.backup)`: хранилище переподключалось на новый объект, а контейнер, `EventRouter` и фабрика FSM держали исходный. Проверено: до reload 1 автомат по тестовой лампе, после reload **всё ещё 1**
- **Дефект 3 — перестроения не было.** Эндпоинт не пересобирал ни машины состояний, ни карту маршрутизации
- **Связь с K7:** до починки двойной сборки дефект был неразличим — reload работал с хранилищем того приложения, которое отдавало интерфейс, а оно было собрано на манифесте из образа
- **Решение** (выбор делегирован владельцем): перечитывание идёт **в тот же объект** манифеста, поэтому держатели видят изменение без пересборки приложения; автоматы пересоздаются с `restore_state=True`, чтобы лампа, включённая по движению, не «забывала» об этом; карта маршрутизации перестраивается
- **`reload_into()` сначала разбирает файл во временный объект и только затем заливает в цель:** частично применённый манифест хуже отказа. Проверено тестом — после сбоя разбора платформа остаётся на прежнем манифесте
- **Границы полномочий зафиксированы намеренно:** reload откатывает манифест, **а не** хранилище устройств. Откат хранилища не заявлен, и делать это молча опаснее, чем не делать
- **Про чувствительность тестов — дважды поймал себя:** (1) первый прогон инъекций дал `9 passed` на каждой из трёх правок — значение переменной в цикле начиналось с пробела, ни один `case` не совпал, **инъекции просто не применялись**; (2) после исправления цикла маршрутизация и снятие лишних автоматов всё ещё не ловились — они не были заявлены вовсе, проверки добавлены; обновление «по частям» (только `rooms`) тоже прошло незамеченным — добавлены проверки на правила и описание дома вне секции комнат
- **Проверено запуском контейнера без перезапуска процесса:** комната убрана из файла вручную → reload → `Unregistered FSM for entity light.reload_probe_lighting_10`, автоматов 9; затем добавлена обратно → reload → автоматов 10, `комнат 6, автоматов 10`
- **Собственный дефект в логе, найденный при проверке:** `logger.info` с `%d` не подставляет значения (loguru использует формат `{}`), строка выводилась буквально. Исправлено
- **Статус:** ✅ Исправлено в specs/009 (2026-10-05), коммит `86c945f`


### #69 — `POST /api/v1/devices/{id}/command` отвечал «executing» и ничего не выполнял · Low
*(выявлено 2026-10-05 при начале пункта 3 веб-плана, исправлено 2026-10-05, спека 009)*
- **Файлы:** `src/webui/routes/devices/devices.py` (`execute_device_command`), `src/services/device_service.py` (`_call_ha_service`), `src/adapters/mock_adapter.py`, `src/core/models/device_sync_event.py` (`command_failed`), `tests/contract/test_device_command_execution.py` (новый, 6)
- **Класс:** ложный успех — тот же, что #65
- **Суть:** в обработчике стоял `# TODO: Использовать DeviceService.execute_command()`. Он генерировал `command_id`, писал событие аудита и отвечал `status="executing"`. Вызова сервиса HA не было. Рабочий `_call_ha_service` существовал и не вызывался
- **Доказательство до починки:** `POST /command` с `light.turn_off` для реальной лампы → **202** `{"status": "executing", ...}`; состояние лампы в HA до и через 4 с после — `on`
- **Что сделано:** команда вызывается через `_call_ha_service`; ответ — **200** со `status="success"` и заполненным `completed_at`, либо **502** с текстом ошибки HA. Статус `executing` больше не выдаётся
- **Контракт ответа изменён намеренно**, и пять файлов проверок обновлены под фактическое поведение: `test_devices_api.py`, `test_access_control.py` (оба), `test_device_access_rights.py`, `test_concurrency_and_removal.py`, `test_device_audit_log.py`. Замена 202 → 200 затрагивала только маршрут команды
- **Три дефекта найдены по ходу и исправлены:** (1) пустой словарь параметров считался ложным и подменялся на `request.data` (None), после чего `**None` ронял вызов с `TypeError`; (2) `_call_ha_service` нормализовал ответ как `bool(result)`, а HA на вызов сервиса отвечает **списком** — пустым, если состояние уже было нужным, — из-за чего `bool([])` давал `success: False` при успешно выполненной команде, то есть тот же ложный исход; (3) `MockAdapter.call_service` принимал только `data`/`context`, тогда как `HAAdapter` принимает `**kwargs`, и заглушка падала с `TypeError` на любой команде с параметрами — расхождение с production-адаптером, скрывавшее проблему
- **Добавлено действие аудита `command_failed`:** провал раньше не попадал в журнал, потому что команда не выполнялась вовсе
- **Чувствительность проверена инъекциями** (восстановление по sha256): возврат заглушки роняет 4 теста; неотбрасывание домена из имени — 1; ошибка HA, выдаваемая за успех — 1
- **Ошибка в моих тестах:** первая редакция подменяла адаптер в конструкторе `DeviceService`, но приложение к тому моменту уже собрано, и адаптер оставался `MockAdapter` — тесты падали не по той причине, что проверяли. Подмена перенесена на живой экземпляр
- **Проверено запуском контейнера на реальной лампе:** лампа `off` → `POST /command` с `turn_on` → **200**, `status: success`, лампа **`on`**
- **Часть 2 — команда через автомат** (сделано 2026-10-05, коммит `a2c2e76`). Команда сначала отдаётся автомату событием `manual_switch_on`/`manual_switch_off`, и действие шаблона само вызывает HA. Команда не выполняется дважды, состояние совпадает с реальным. При отсутствии ручного перехода команда уходит в HA напрямую, а ответ сообщает `automation_synced: false` — молча разъезжаться нельзя, но и отказываться нельзя: ручных переходов нет ни в одном шаблоне, кроме `lighting` и `night_light`
- **Доказательство вживую:** `turn_on` → `automation_synced: true`, автомат `OFF → ON_MANUAL`, лампа включилась. **Датчик движения при ручном режиме не перебил состояние** — автомат остался `ON_MANUAL`. Затем `turn_off` → `OFF`, лампа погасла. Лампа возвращена в исходное `on`
- **Дебаунс шаблона распространяется и на ручные команды:** `lighting.yaml` задаёт `debounce_sec: 0.5`, поэтому вторая команда в пределах полсекунды отвергается движком как дребезг. Это верное поведение, а не дефект; учтено в тесте паузой. **Для интерфейса это значит, что кнопку надо гасить на время дебаунса**, иначе второе нажатие выглядело бы как «не работает»
- **Чувствительность проверена инъекциями** (восстановление по sha256): «всегда считать обработанным автоматом» роняет 2 теста; «никогда не отправлять событие» — 4; «всегда рапортовать `automation_synced: true`» — 1
- **Моя ошибка в тесте:** первая проверка выключения ждала ноль миллисекунд между командами, и движок справедливо отвергал вторую как дребезг. Тест исправлен паузой больше `debounce_sec`
- **Часть 3 — кнопка на карточке** (сделано 2026-10-06, коммит `357c6bc`). Кнопка «Включить»/«Выключить» для доменов light/switch/fan/input_boolean, отправляет `POST /api/v1/devices/{id}/command`. Идентификатор устройства берётся из выгрузки `/api/v1/devices` по `entity_id`, потому что карточки размечены `entity_id` из Home Assistant, а маршрут ждёт внутренний UUID
- **Пауза 900 мс после команды:** шаблон `lighting` задаёт `debounce_sec: 0.5`, и вторая команда в пределах этого окна отвергается движком как дребезг. Без паузы второе нажатие выглядело бы как «не работает». Тест сверяет паузу со значением `debounce_sec` из самого шаблона, чтобы его правка не оставила кнопку бесполезной молча
- **Исход команды виден:** при `automation_synced: false` кнопка показывает «автоматика не следит» с пояснением, что автомат о состоянии устройства не знает. Ошибка команды показывается текстом
- **Проверено запуском контейнера:** кнопка присутствует в отданной странице; `turn_on` дал `automation_synced: true`, гирлянда загорелась, автомат перешёл в `ON_MANUAL`; выключение вернуло `off`
- **Про чувствительность:** четыре из пяти первых инъекций сработали; первая — «убрать вставку кнопки из карточки» — прошла молча, потому что проверки смотрели на весь файл и находили там `device-power` и `deviceIdByEntity`. Добавлена проверка по телу `renderDeviceState`: требуется именно вставка управления и подключение обработчика
- **Статус:** ✅ Пункт 3 закрыт — маршрут команды выполняется и сообщает исход, состояния не расходятся, кнопка работает


### #70 — Потеря связи с Home Assistant не восстанавливается: платформа молча перестаёт реагировать · Low
*(выявлено 2026-10-05 при переключении стенда на другое устройство)*
- **Файлы:** `src/adapters/ha_adapter.py` (прослушивание и переподключение), `src/webui/routes/readiness.py` (проверка), `src/services/watchdog.py`
- **Класс:** тихая остановка. Платформа продолжает отвечать `200` на `/health` и отдавать страницы, но ни одно событие Home Assistant больше не обрабатывается
- **Доказательство запуском:** после ~15 минут работы журнал сторожа стабильно показывал `"ha_disconnected": true, "result": "degraded"`, `GET /ready` — `ready: false`, `failed: ["home_assistant"]`, `{"ok": false, "detail": "нет соединения с Home Assistant"}`. При этом **изнутри контейнера HA отвечает `200`** — то есть дело не в Home Assistant и не в сети, а в том, что адаптер не переподключается. Журналов о попытке переподключения нет вовсе: ни `disconnect`, ни `reconnect`, ни `backoff`
- **Как обнаружено:** стенд переключён с рабочего света на `light.girlianda_na_oknakh`; переход по движению не сработал, `Routing:` в журнале отсутствовал. Первая догадка — ночной guard `is_day_time`. Оказалось неверно: события не доходили вовсе
- **Что помогает:** только перезапуск процесса. После `docker compose restart` `ready: true`, `home_assistant: {"ok": true}`, события пошли (`Routing: sensor=… → fsm=…_lighting_10, event=motion_detected`)
- **Почему это опаснее всего остального, что найдено за сессию:** `/health` отвечает `200`, интерфейс работает, страницы рисуются — выглядит как «всё живо». Расхождение видно только в `/ready` и стороже, а их никто не опрашивает автоматически. Устройство при этом не реагирует ни на что
- **Что, вероятно, надо:** разобрать `ha_adapter` — задача прослушивания завершается, а переподключение не инициируется, хотя юнит-тесты `tests/test_ha_adapter_reconnect.py` (6 тестов на backoff и обрыв) есть и проходят. Похоже, тесты проверяют прослушивание изолированно, а в реальном цикле задача глохнет иначе
- **Как выглядит в проде:** контейнер простоял **10 часов** без связи с HA, показывая `healthy` (Docker смотрит `/health`, а он отвечает 200). Всё это время события не обрабатывались, и заметить можно было только по `/ready` и сторожу
- **Исправлено (2026-10-05, коммит `eec3504`):** отсутствие живой задачи чтения трактуется как обрыв — обрыв фиксируется, цикл повторяет подключение с backoff, тем же путём, что при штатном завершении задачи
- **Проверено частично, и это важно оговорить.** На живом коде подтверждено, что цикл повторных подключений работает: пробный контейнер с недоступным HA сделал 11 попыток за 55 с и остался жив. Но **конкретная исправленная ветка — «соединение установлено, задача чтения умерла» — вживую не воспроизведена**: для этого нужен разрыв уже установленного соединения. Чувствительность теста инъекцией подтвердить не удалось (заглушка подменяет `connect` целиком и нужную ветку не достигает)
- **Как проверять дальше:** fixed-образ развёрнут 2026-10-06, соединение установлено (`ready: true`). Если соединение оборвётся, в журнале должны появиться `WebSocket lost` и `retrying in Ns` вместо тишины — это и есть доказательство. Проверка: `docker compose -f deploy/docker/docker-compose.prod.yml logs -f behavioral-platform | grep -E "WebSocket lost|retrying"`
- **Мою первую версию причины пришлось исправить:** я заявил, что у HA-клиента нет поля `_listen_task`. Неверно — поле есть у `SimpleHAWebSocketClient` (он и используется). Второй клиент `HAWebSocketClient`, с `listen()` и без этого поля, в сборке не используется вовсе

- **ВОЗВРАТ ДЕФЕКТА 2026-10-06: починка закрыла только один из двух путей висяния.** fixed-образ отработал около четырёх часов и снова отвалился от HA. За всё это время в журнале адаптера **ровно одна строка**: `HAAdapter: No events for 300s, connection is stale - forcing reconnect` — и ни одной попытки переподключения после неё
- **Второй путь висяния (подтверждён, причину довести не успел).** Heartbeat (`_heartbeat_loop`) при отсутствии событий 300 с ставит `connected = False`, закрывает WebSocket-клиент и делает `continue` — по замыслу «форсирует переподключение». Разрыва соединения достаточно, чтобы основной цикл заметил: задача чтения завершается, и закрытая ветка должна сработать. Она не сработала: ни `WebSocket lost`, ни `retrying`, ни `attempting WebSocket connection`. Обещание в тексте лога не выполняется
- **Почему это важно для оценки правки:** исправленный ранее путь — «задача чтения уже мертва к моменту ожидания». Heartbeat идёт другим маршрутом: он закрывает клиент из отдельной задачи, и по журналу видно, что основной цикл на это не отреагировал. Правка его не покрывает
- **Две версии причины, которые предстоит проверить локально, без вашего HA:** (а) задача, порождающая переподключение, к моменту обрыва уже завершена и её никто не перезапускает; (б) `close()` ждёт `_listen_task` из heartbeat-задачи, а та не завершается
- **ОБНОВЛЕНИЕ 2026-10-06, вечер: инструментация была слепой, причина локализована.**
- **Мой дефект в диагностике.** Инструментацию я добавил на уровне `info`. Логи `adapters.ha_adapter` не имеют собственного обработчика и наследуют корневой, где `info` не виден: проверено на живом контейнере, от этого модуля в журнале **ноль** строк. Инструментация молчала и не могла ответить на вопрос, для которого сделана. Все прежние выводы, построенные на «журнал замолкает», опирались на этот недействительный посылк. Обе записи переведены на `warning`, уровень теперь проверяется кодом (возврат `info` роняет проверку)
- **Срабатывание частое, а не редкое:** обрыв приходит примерно через 5 минут после старта контейнера, а не раз в 4 часа. Редкость была видимой только потому, что в журнале не было видно ничего, кроме предупреждения. Воспроизводится на каждом старте — ждать не нужно
- **Данные видимого прогона (15:17:38):** две строки — `forcing reconnect` и `closing stale connection` — с разницей **57 микросекунд**. Записи `stale connection closed` нет **вообще**. Значит ветка пройдена, закрытие начато, а heartbeat из `await self._ws_client.close()` **не возвращается**
- **Поправка к моему прежнему выводу:** `PING`/`PONG` каждые 20 с после срабатывания идут от автопинга библиотеки, а не от нашего heartbeat (интервал 30 с, и после `connected = False` он замолчал бы). На них я ошибочно строил вывод, что heartbeat жив
- **Переподключения нет:** нового рукопожатия (`Upgrade`, `connection open`, `auth_required`) после ветки нет, при том что сокет остаётся открытым и отвечает. Журнал обещает переподключение, которого не происходит
- **Снаружи не видно:** `/health` и `/ready` отвечают 200, поэтому платформа выглядит здоровой, хотя события Home Assistant уже не получает. Это опаснее явной ошибки
- **Два кандидата, различить локально не удалось:** (1) `close()` застревает на `await self._listen_task` (строка 132) — отмена задачи чтения не приводит к её завершению, тогда стоят и heartbeat, и основной цикл, а сокет остаётся открытым, что совпадает с наблюдаемым; (2) задачу heartbeat кто-то отменяет между двумя записями. Моя попытка построить локальную модель этого сценария была ненадёжной, поэтому кандидат 1 остаётся гипотезой
- **ЛОКАЛИЗОВАНО ТОЧНО 2026-10-06 15:33:52 — застревание в `await self.ws.close()`. Первый кандидат опровергнут.**
- **Полная последовательность записей (живой стенд):**
  ```
  .339489 No events for 300s, connection is stale - forcing reconnect
  .339534 closing stale connection
  .339793 close() start, listen_task=<Task pending>          <- вызов 1, из heartbeat
  .339842 close() cancel sent, task done=False
  .340026 close() listen_task awaited, done=True             <- 184 мкс, отмена сработала
  .340035 close() closing websocket                          <- выхода нет никогда
  .340999 close() start, listen_task=<Task cancelled>       <- вызов 2, из основного цикла
  .341039 close() cancel sent, task done=True
  .341043 close() listen_task awaited, done=True
  .341249 close() closing websocket
  .387132 close() websocket closed                           <- выход вызова 2 через 46 мс
  ```
- **Кандидат 1 («застревание на `await self._listen_task`») опровергнут:** отмена задачи чтения отрабатывает за 184 микросекунды, задача завершается. Моя гипотеза была неверна и стоила бы неверной правки
- **Застревание — в `await self.ws.close()`:** вызов 1 доходит до закрытия сокета и не возвращается, его записи `websocket closed` нет до сих пор. Вызов 2 из основного цикла на том же сокете завершился через 46 мс: закрытие возможно, но требует чужого прогресса — похоже на ожидание рукопожатия закрытия, которое не приходит
- **Переподключения нет:** после ветки ноль рукопожатий (`Upgrade`, `connection open`, `auth_required`), `PING` продолжает идти. Сокет жив на уровне TCP, heartbeat застрял, основной цикл ушёл в очистку и к повторному подключению не пришёл
- **Снаружи не видно:** `/health` и `/ready` отвечают 200. Платформа выглядит здоровой, не видя событий Home Assistant, — это хуже явной ошибки, потому что сторож не срабатывает
- **ПРАВКА С ТАЙМАУТОМ СДЕЛАНА И НЕ ПОМОГЛА — 2026-10-06 15:48. #70 НЕ закрыт.**
- **Что сделано:** `await self.ws.close()` ограничен `asyncio.wait_for` на 5 с, по истечении пишется запись и закрытие продолжается. Проверка требует обеих сторон: на молчащем сокете `close()` возвращается за разумное время, на штатном — сокет закрывается и клиент помечен закрытым. Без ограничения проверка падает по таймауту, то есть ловит ровно то висяние, что наблюдалось
- **Что показал живой прогон:** картина не изменилась. Первый вызов `close()` доходит до `closing websocket` и не пишет ни `websocket closed`, ни `timed out`. Второй вызов из основного цикла закрывает сокет за 92 мс. Рукопожатий после ветки по-прежнему **ноль**, переподключения нет
- **Почему таймаут не сработал — это и есть ответ:** heartbeat **отменяется** основным циклом прямо посреди `ws.close()`. `CancelledError` — не `Exception`, мои обработчики его не ловить и не должны; отменённая задача просто исчезает без записи. Значит верен **кандидат 2**, а не первый: виновата не зависшая отмена задачи чтения (она отрабатывает за 184 мкс), а отмена задачи heartbeat со стороны очистки основного цикла. Ограничение по времени здесь не помогает по существу
- **Поправка к моему прежнему утверждению:** я писал, что «`/ready` отвечает 200, поэтому платформа выглядит здоровой». Это было неверно — я смотрел на код ответа, а не на тело. После срабатывания `/ready` отдаёт **`ready: false`**, «нет соединения с Home Assistant». Готовность дефект видит; невидимым его делает именно HTTP 200 при `ready: false`, а не отсутствие реакции
- **ЧТО ОСТАЛОСЬ ЧИНИТЬ: цикл переподключения не доходит до `connect()` (2026-10-06, разбор пути).**
- **Доказано проводным журналом:** за весь срок контейнера `connection open` встречается **ровно один** раз. Ни одного второго рукопожатия, ни одной повторной подписки. То есть после срабатывания heartbeat попытка подключения не делается вообще — а не «делается и неудачна»
- **Что успел сделать цикл:** `_record_disconnect` вызван, внутренний `finally` отменил heartbeat (это видно по тому, что его `close()` не дописал `websocket closed`), внешний `finally` выполнил `_cleanup_websocket()` — второй вызов `close()` закрыл сокет за 92 мс и дописал `websocket closed`. После этого путь должен был дойти до `await asyncio.sleep(reconnect_delay)` и следующей итерации с `connect()` — и не дошёл
- **Все сообщения этого пути невидимы:** `retrying`, `attempting WebSocket connection`, `connecting`, `subscribed`, `backoff reset` печатаются либо через модульный `logger` на уровне `info`, либо через per-connection логгер `self._get_logger(...)`, который в этом развёртывании **не даёт ни одной строки**. Поэтому вывод «цикл ничего не пишет, значит он остановился» здесь недопустим — отсутствие строк ничего не доказывает. Проверено прямо: `HAAdapter: connecting` и `HAAdapter: subscribed` в журнале отсутствуют **и при успешном старте**
- **Что уже исключено:** сторож (`src/services/watchdog.py`) ничего не останавливает — только наблюдает (`set_ha_connection_lost`, `record_fsm_stuck`), вызовов `shutdown`/`stop` в нём нет. `stop()` у адаптера вызывается только из `container.py:71` при остановке и из CLI `bulk_import`, в рантайме — ни разу
- **ПРИЧИНА УСТАНОВЛЕНА 2026-10-06 16:12:53 — цикл выходит по отмене извне. Повторного подключения не будет НИКОГДА.**
- **Доказано видимым прогоном.** Записи цикла сделаны наблюдаемыми (уровень WARNING), полная последовательность:
  ```
  16:12:53.767  No events for 300s ... forcing reconnect
  16:12:53.769  close() closing websocket                  <- heartbeat закрывает сокет
  16:12:53.770  reconnect loop cancelled - no retry will happen   <- ОСНОВНОЙ ЦИКЛ ВЫХОДИТ ПО ОТМЕНЕ
  16:12:53.770  close() start, <Task cancelled>             <- _cleanup_websocket в finally
  16:12:53.905  close() websocket closed
  16:12:53.906  reconnect loop exited
  ```
  Итераций цикла за весь срок контейнера — **одна** (на старте). Ни `retrying`, ни `backoff skipped` не печатались.
- **Что это значит:** основной цикл попадает в `except asyncio.CancelledError: break` — то есть его задачу отменяют извне, и он выходит вместо повторного подключения. Именно эта ветка и была последним невидимым местом: она печаталась на `info`, поэтому её отсутствие ничем не отличалось от зависания. Теперь она WARNING и проверяется кодом
- **Временная связь точная:** отмена приходит через ~1.5 мс после того, как heartbeat начал закрывать сокет, то есть сразу после `heartbeat_task.cancel()` во внутреннем `finally`. По устройству кода `await heartbeat_task` подавляет первую отмену, а следующее ожидание (`await self._cleanup_websocket()`) снова выбрасывает `CancelledError` — и его ловит внешний обработчик с `break`
- **ЗАКРЫТ 2026-10-06 16:32. Причина: `listen_task.result()` на отменённой задаче.**
- **Механизм (точный):** heartbeat при устаревшем соединении отменяет задачу чтения. Основной цикл это видит и вызывает `listen_task.result()`, чтобы узнать причину. На **отменённой** задаче `result()` бросает `asyncio.CancelledError`, а он **не наследует `Exception`** — значит `except Exception` его не ловил. Исключение уходило в обработчик отмены самого цикла, тот делал `break`, и переподключения не происходило **никогда**. Отмена задачи чтения — ожидаемый исход закрытия устаревшего соединения, то есть обрыв, а не остановка платформы
- **Почему это не выдало себя раньше:** внешней отмены не было вовсе. `stop()` и `Container.shutdown()` при срабатывании не вызываются — проверено тем, что обе записи сделаны видимыми и не появились. Я держался гипотезы «отмена извне», потому что отмена **выглядела** внешней: тот же `CancelledError`, тот же выход из цикла
- **Починка:** классификация вынесена в `_listen_task_reason()`, где отменённая задача даёт `listen task cancelled`, упавшая — `listen task failed: ...`, завершившаяся — `listen task ended`. Отдельный метод, а не три строки в цикле: различать `CancelledError` и обычные ошибки здесь обязательно, а при следующей правке в теле цикла различение снова потерялось бы
- **Проверено живьём:** после срабатывания в 16:32:18 появились `WebSocket lost (listen task cancelled), reconnecting (attempt 1, ...)`, затем `retrying in 1.0s`, затем **новая итерация** `attempting WebSocket connection (iteration)` в 16:32:19, а счётчик `connection open` вырос с 1 до **2**. События Home Assistant пошли снова
- **Проверка (5 штук) берёт настоящие задачи asyncio** — отменённую, упавшую, завершившуюся: подменять их заглушками нельзя, весь дефект именно на отменённой задаче. Отдельная проверка требует, чтобы метод **не выпускал** `CancelledError` наружу: иначе при следующей правке дефект вернётся незамеченным, если проверка останется только на текст. Возврат `except Exception` роняет 2 проверки
- **Что осталось в коде как страховка, а не как починка:** ограничение `ws.close()` по времени на 5 с. Причина была не в нём; оставлено, потому что ожидание рукопожатия закрытия без предела — плохая практика
- **Отдельно для истории:** всё это заняло пять итераций, потому что три записи подряд были на `info` и были не видны. Первая инструментация не могла ответить на вопрос, для которого была сделана, а выводы строились на её молчании
- **Следующий шаг (дешёвый и однозначный):** сделать видимыми `stop()` и вход в `Container.shutdown()` на уровне WARNING с отметкой времени, затем один прогон (6 минут). Если запись появится в момент отмены — причина найдена окончательно; если нет — отмена приходит изнутри, и следующий кандидат — код, отменяющий задачу вне `stop()`
- **Что уже можно утверждать:** ограничение закрытия по времени и отмена задачи чтения были не причиной. Причина — выход основного цикла по внешней отмене. Править нужно не `close()`, а путь выхода из цикла: отмена не должна приводить к отказу от переподключения
- **Почему не сделал в этом заходе:** нужна ещё одна итерация развёртывания с ожиданием 6 минут, а бюджет контекста на исходе. Оставляю дерево без непроверенных изменений; наблюдаемость `#connect()` и выхода из цикла — следующий шаг, он дешёвый и даёт ответ сразу
- **Почему не сделал сейчас:** правка затрагивает и штатное закрытие соединения, а подтвердить её можно только живым прогоном. Фиксирую факты, чтобы не оставить в дереве непроверенное изменение
- **Что сужает круг:** heartbeat логирует раз в 30 с на уровне DEBUG, поэтому отсутствие строк после `forcing reconnect` означает, что задача heartbeat **перестала доходить до следующей итерации** — то есть зависла внутри `await self._ws_client.close()`. Там сначала отменяется и **ожидается** `_listen_task`. Если та не завершается по отмене, замирает и heartbeat, и основной цикл (он ждёт ту же задачу) — а это ровно наблюдаемая картина
- **Проверка, которая это подтвердит или отвергнет:** дать соединению оборваться по-настоящему и посмотреть, завершается ли `SimpleHAWebSocketClient.close()`. Либо инструментировать `close()` по шагам — тогда следующее повторение покажет, где именно встало
- **Что предлагаю сделать перед правкой:** ограничить `close()` таймаутом и добавить запись журнала сразу после «форсирует переподключение». Это не меняет поведение, а превращает немую остановку в наблюдаемую: следующее повторение скажет точно, где застряло. Правку поведения (что именно делать при зависшем закрытии) принимать надо с этими данными, а не вслепую

- **ДИАГНОЗ 2026-10-06 вечер: почему `hysteresis` нельзя просто «оживить».** В шаблоне
  `src/features/climate_control.yaml` **нет ни одного guard'а** — все четыре перехода
  срабатывают чисто по событию (`temperature_low`, `temperature_high`,
  `temperature_reached`). Параметр, выражающий полосу вокруг целевой температуры,
  требует, к чему привязать проверку, и привязывать не к чему: единственное, где
  условие может быть выражено, — guard на переходе
  `HEATING -> IDLE` / `COOLING -> IDLE` по `temperature_reached`
- **Что это значит по существу:** без guard'а обогрев выключается на самой целевой
  температуре, то есть система циклит (короткие циклы). `hysteresis` — это как раз
  лекарство от этого, поэтому параметр осмыслен и место ему есть
- **Предлагаемая починка (требует отдельной сессии, не сделана здесь):**
  1. спека и тесты: `temperature_reached` должен давать `IDLE` только если
     `current >= target_temp - hysteresis` для обогрева и `current <= target_temp + hysteresis`
     для охлаждения; пустой параметр — нынешнее поведение (без полосы);
  2. новый guard в `src/core/guards/builtin.py` + регистрация в реестре;
  3. правка шаблона `climate_control.yaml` — guard'ы на двух переходах в `IDLE`;
  4. `target_temp` и `hysteresis` в `CONTRACT.yaml` переводятся в `effective: true`
     **после** того, как код их прочитает; сейчас `effective: false`, и это честно;
  5. регенерация контракта (генератор параметры теперь сохраняет, #72) и проверка
     действенности в обе стороны;
  6. живая проверка на реальном термостате HA — без неё параметр снова окажется
     «принимается и хранится», то есть тем же классом дефекта
- **Почему не сделал в этом заходе:** правка затрагивает guard, реестр, шаблон,
  контракт и требует живого подтверждения на устройстве. Сделать это под конец
  сессии без времени на проверку — значит оставить непроверенное изменение в
  дереве. Диагноз зафиксирован, чтобы следующая сессия начинала не с «сделать
  параметр рабочим», а с конкретного места и конкретного смысла


### #71 — Большинство параметров поведения в манифесте ни на что не влияет · Low
*(выявлено 2026-10-06 при начале пункта 4 веб-плана)*
- **Файлы:** `src/core/fsm/factory.py:165` (`_apply_params_to_template`), `src/core/fsm/factory.py:227`, `src/features/lighting.yaml`, `src/core/guards/builtin.py:135`
- **Класс:** параметр принимается, хранится и не используется. Тот же класс, что #65 и #69: обещание без результата, только в конфигурации
- **Суть:** `BehaviorConfig.params` через `_apply_params_to_template` попадают в `template_data["params"]`, то есть params лежат в описании автомата. Но читают их не все
- **Разбор по параметрам (проверено чтением мест использования):**
  - `brightness` — **работает**: читается в `action_handlers.py:63` (`turn_on_light`, `turn_on_night_light`) и попадает в команду HA
  - `humidity_threshold` — **работает**: читается в guard `builtin.py:135`
  - `motion_timeout_sec` — **не работает**: читается только в `manifest_generator.py:80` и в валидаторе. Таймаут перехода берётся из YAML шаблона (`factory.py:227`: `timeout_sec=yaml_transition.timeout_sec`), параметр в это выражение не входит. В `lighting.yaml` стоит жёсткое `timeout_sec: 30.0`
  - `target_temp`, `hysteresis` — **не работают**: в горячем пути (фабрика, действия, guard'ы) не упоминаются вовсе. `climate_heat` вызывает `set_temperature` **без** целевой температуры — параметр из контекста не берётся
  - `schedule` — **работает** (поправка первой редакции записи): фабрика при наличии `schedule` в params вешает guard `is_within_schedule` (`factory.py:319`, `guards/schedule_guard.py`). Первая редакция записи назвала его инертным — ошибка проверки, искавшей только в валидаторе
- **Почему это блокирует пункт 4:** форма параметров, построенная поверх манифеста, предложила бы пользователю поля, изменение которых ничего не меняет. Ровно тот класс дефекта, который закрыт в #65, #66, #69, и здесь он был бы в самом интерфейсе. Сначала надо решить, какие параметры **должны** влиять, и только потом рисовать поля
- **Что нужно решить (владельцу):** (а) оживить параметры — переходы должны брать `timeout_sec` из params, а действия — `target_temp`/`hysteresis`; (б) оставить как есть и в контракте шаблонов отметить параметры как инертные, чтобы форма их не предлагала; (в) разделить: показывать только те, что работают, остальные — в JSON с пометкой
- **Частично пересекается с #67:** там зафиксировано, что порог влажности зашит в имя guard'а `humidity_above_60`. Уточнение после проверки: guard **читает** `humidity_threshold` из контекста, то есть параметр применяется — расходится именно имя (`60` в имени против значения 65 из манифеста), из-за чего название вводит в заблуждение, а не поведение
- **Уточнение 2026-10-07 (спека 010): `humidity_threshold` работал всегда, но данных не получал.** Порог читался из контекста корректно — и в контекст никто не клал само значение влажности: маршрутизатор передавал только имена состояний. То есть параметр применялся к пустому месту, и вентиляция не могла сработать. Исправлено в спецификации 010 (US2): значение датчика кладётся в контекст под именем роли, а требование условия проверяется отдельно, чтобы «данных не было» не путалось с «значение не подходит». Это тот же класс, что у #9 и #18: механизм есть, данных ему никто не передаёт
- **Разбор уточнён (2026-10-06):** `schedule` **работает** — фабрика при наличии этого параметра вешает guard `is_within_schedule` (`factory.py:319`, `guards/schedule_guard.py`). Первая редакция записи назвала его инертным: ошибка проверки, искавшей чтения только в валидаторе. Окончательно инертны `motion_timeout_sec`, `target_temp`, `hysteresis`
- **Основа для пункта 4 сделана:** контракт шаблонов получил раздел `params` с типом, диапазоном, пояснением и **меткой `effective`**, а метка проверяется кодом в обе стороны — `true` обязан читаться в горячем пути, `false` обязан не читаться. Иначе форма построилась бы по обещанию документа, а не по коду
- **Генератор:** `tools/add_param_contract.py` (поверх `tools/gen_template_contract.py`)
- **Тесты:** 5 в `tests/contract/test_behavior_param_effectiveness.py`. Чувствительность проверена инъекциями: метка `false` на рабочем параметре, метка `true` на нерабочем и удаление параметра из контракта — каждая роняет тест
- **Тест на покрытие манифеста:** каждый параметр из `deploy/docker/config/manifest.yaml` обязан быть описан в контракте — неописанный молча пропадёт при перезаписи поведения
- **Статус:** 🟡 Частично закрыто — инертность зафиксирована и защищена проверкой; сами параметры не «оживлены», форма поведения не построена


### #72 — ЗАКРЫТ 2026-10-06


### #73 — ЗАКРЫТ 2026-10-06 — станок прогонялся против боевого контейнера

**Обнаружено:** 2026-10-06, при браузерной проверке формы правки поведений.

**Что произошло:** станок поднимает свой сервер только если порт свободен, и
проверял это одним вопросом «отвечает ли порт». На 8125 уже висел запущенный
контейнер платформы, поэтому станок молча пошёлл против него: тесты получали
боевой манифест и боевой Home Assistant. Отказы браузерных проверок были
отказами боевой системы, а не станка — и это выглядело как дефект формы.

**Состояние данных:** вреда нет. Проба до записи не дошла: отказ случился на
`PUT /behaviors` для чужого устройства (`update.home_assistant_supervisor_update`),
потому что фильтр `?ha_entity_id=` в `/api/v1/devices` не действует (см. #74).
Манифест в томе контейнера не изменился: у `light.kitchen` на месте
`brightness: 255`, `motion_timeout_sec: 180`, 10 датчиков, 4 комнаты, 6 устройств.
Источник «E2E Home Assistant» не создан — станок взял существующий.

**Исправлено:** станок отвечает меткой в `/health`, и переиспользовать можно
только сервер с этой меткой; порт вынесен с 8125 на 8177.


### #74 — ЗАКРЫТ 2026-10-06 — фильтр `?ha_entity_id=` в `/api/v1/devices`


### #75 — ЗАКРЫТ 2026-10-06 (полностью)

Закрыто вместе с двумя вещами, которые раньше были помечены как невыясненные.

**1. Четыре падения — проверки, прибитые к старой копии манифеста, а не дефекты платформы.**
`page.request` не наследует заголовки страницы, поэтому запрос `/api/fsm/state` шёл
без `X-User-ID` и получал 401, а вторая проверка падала с `KeyError: 'states'` — то
есть на «состояниях» без причины. Требование идентичности проверялось и до этого
отдельно (tests/contract/test_fsm_state_access_default.py:57). Третья проверка была
прибита к `light.kitchen` — автомату из старой копии манифеста; идентификатор теперь
берётся из живых данных, и проверка требует наличия автоматов, иначе она пуста.

**2. Таймаут `Page.goto` — устранён.** Причина: ожидание события `load`, которое
наступает только после загрузки htmx, Bootstrap и mermaid с CDN. При медленной сети
событие не наступало за 30 с, и падал `Page.goto` без связи с проверяемым. Заменено
на `domcontentloaded`: нужные скрипты проверяются явными ожиданиями. Побочный
эффект — время прогона файла упало с ~72 с до ~44 с.

**3. Гонка при открытии панели правки — устранена.** Кнопка «Поведения» полагалась
на то, что данные устройств уже пришли: карточки комнат рисуются из манифеста, а
`/api/v1/devices` приходит позже, и до его ответа кнопки на карточке нет — панель
не открывалась при успешном предыдущем шаге. Теперь `_open_editor` ждёт непустой
`window.devices` перед кликом.

**Сторож на эти правки НЕ добавлен — осознанно.** Сначала добавлен класс с проверками
по исходному тексту станка, но он оказался самоотсылающимся: текст проверки
удовлетворял её же утверждение, и удаление ожидания из кода проходило незамеченным —
это показала инъекция. Попытка сузить поиск телом функции не помогла по той же
причине. Такой сторож выглядел бы защитой, не проверяя ничего, поэтому удалён.
Правки подтверждены двумя прогонами подряд: 29 passed.

Итог: 29 passed стабильно; ранее 4 падения и два редких сбоя.


### #76 — Ложный обрыв каждые 5 минут на тихом доме (закрыт 2026-10-06)

**Суть.** Heartbeat объявлял соединение устаревшим через 300 секунд после
последнего **события**. Но `_last_event_time` выставлялся только при подключении и
**нигде не обновлялся** — ни на входящем сообщении, ни на успешном ответе на ping.
Поэтому обрыв объявлялся ровно через 300 с после старта независимо от активности
дома: тишина в доме и мёртвое соединение были неразличимы, а ложный обрыв рвал
исправное соединение, после чего `/ready` успевал вернуть `ready: false`.

Это стало видно при разборе #70: срабатывание повторялось через 300 с в каждом
прогоне, и я принял это за «ночной обрыв HA», пока не сверил время с временем
старта контейнера.

**Починка, два шага — оба обязательны.**
1. Признак жизни (`_last_liveness_time`) обновляется при подключении, на каждом
событии и на каждом успешном ответе на ping. Ответ на ping — прямое доказательство
жизни.
2. **Порядок в цикле перевёрнут: сначала признак жизни, потом вывод.** Это главная
часть. При прежнем порядке (сначала судить по тишине, потом спрашивать сокет)
вывод всегда опережал проверку: при очередном пробуждении тишина уже «пять минут»,
и соединение рвалось, не успев ответить ни на один ping. Моя первая правка сделала
только первый шаг и на проверке это сразу обнаружилось — ping не отправлялся вовсе,
потому что цикл уходил в ветку устаревания раньше.

**Проверка (3 штуки) берёт настоящий heartbeat**, сон подменён на одну итерацию:
успешный ping обновляет признак жизни; тихий дом не рвёт соединение; **неотвечающий
сокет по-прежнему приводит к обрыву** — иначе починка тишины сломала бы исходную
задачу heartbeat. Инъекциями: возврат ping после проверки устаревания роняет 1
проверку, отказ обновлять признак жизни на ping — 2.

**Проверено живьём:** 8 минут на тихом доме — одна строка адаптера (исходное
подключение), ни одного «forcing reconnect», `ready: true`, «соединение установлено».
Раньше на пятой минуте был ложный обрыв.


### #77 — `SHADOW_MODE` не читалась кодом; режим не был виден оператору (ЗАКРЫТ 2026-10-06)

**Обнаружено:** 2026-10-06, при разборе состояния боевого контейнера перед
пробным запуском с реальными устройствами.

**Суть.** Переменная объявлена в трёх местах (`deploy/docker/.env`,
`deploy/README.md`, `deploy/scripts/deploy.sh`) и **доходит до контейнера** —
проверено: в `.env` стоит `SHADOW_MODE=true`. Но её не читает ни одна строка
Python:

```
$ grep -rn "SHADOW_MODE" --include="*.py" .        # совпадений нет
$ grep -rn "DeploymentManager" src/ --exclude-dir=__pycache__
                                               # совпадений нет, кроме самого файла
```

`src/core/deployment_manager.py` реализован целиком (`DeploymentMode.SHADOW`,
`set_mode`, `log_dry_run_action` с текстом `[DRY RUN] Would execute: ...`), имеет
свои тесты (`tests/test_deployment_manager.py`, 13 тестов) и **не импортируется ни
в `src/main.py`, ни в `src/bootstrap.py`**, то есть не подключён к работающей
платформе вообще.

**Почему опасно.** Оператор читает в `.env` `SHADOW_MODE=true` и в `deploy/README.md`
— «безопасный режим, действия не выполняются», и ведёт себя соответственно. Платформа
при этом выполняет действия. Что уже выполнено вживую и найдено в
`data/state.json`: два перехода с `source: manual_command` и `new_state: on` — то
есть команда ушла в реальный Home Assistant.

**Состояние данных:** вреда нет, команды корректны и обратимы. Свет
`light.svet_nad_stolom` включён с 14:38 и не выключен — но причина в #78, а не в
shadow mode.

**Проводка в коде была сделана 2026-10-06** (коммит `fa29a87`): `Container.deployment`
создаёт `DeploymentManager.from_env()` и передаёт в адаптер, запрет стоит в
`HAAdapter.call_service`. Проверено на живом стенде: контейнер печатает
`Режим развёртывания: shadow (SHADOW_MODE='true')`, в коде контейнера присутствуют
и `from_env`, и передача в адаптер. Требуемая по решению владельца проводка сделана.

**Что оставалось не сделано: режим был виден только одной строкой в журнале при
старте.** Ни `/ready`, ни `/health` о нём не сообщали. Это зеркальная сторона того
же дефекта: тогда оператор считал систему безопасной, а она трогала дом; теперь
платформа может молча блокировать все команды, а оператор видит исправную систему —
события приходят, автоматы считают состояния, `/ready` отвечает `ready: true`, и
только лампы не включаются. Причина не видна нигде, кроме пролитой часами назад
строки в логе.

**Починка.** `check_deployment_mode` в `readiness.py` и включение проверки в
`collect_checks`. В режиме тени готовность **ложная** — система принимает события и
считает состояния, но не исполняет обещанное, — поэтому отвечает `ok: false` и
называет режим вместе с подсказкой, как включить выход. 503 на `/ready` не ломает
healthcheck контейнера: Docker зовёт `/health`, который остаётся всегда 200
(контракт спеки 003 §1, иначе был бы рестарт-цикл).

**Про дефолт.** `SHADOW_MODE` не задана — режим тени, а не активный режим. Иначе
забытая настройка молча включала бы управление реальным домом. То же и для опечатки.
`deploy/README.md` утверждал обратное (`По умолчанию: false`) — обещание, которое
код не выполнял; исправлено на фактическое поведение.

**Проверки, 8 штук.** Режим назван в ответе; тени соответствует `ok: false`; активному
и гибридному — `ok: true`; признак в ответе совпадает с решением ворот для всех четырёх
режимов (расхождение означало бы, что `/ready` врёт в другую сторону); отсутствие
менеджера и контейнера не ломает готовность; проверка попала в сводку. Инъекция
прежнего кода роняет все 8. Прогон: 2453 passed / 0 failed, mypy strict чист, ruff
чист, interrogate 93.1%.


### #78 — Настоящий обрыв сети: heartbeat находил обрыв, но переподключения не было (ЗАКРЫТ 2026-10-06)

**Причина найдена, воспроизведена тестом и исправлена.** Диагноз, записанный
ниже в этом же разделе, был направлен не туда: подозревался цикл подключения, а
дефект был в heartbeat — том самом механизме, который для этого обрыва и написан.

**Механика дефекта, все три звена в коде.**

1. Разрыв без чистого закрытия (отвал Wi-Fi, `docker network disconnect`) не
завершает задачу чтения: `recv()` ждёт данных, которых не придёт никогда.
2. Heartbeat это обнаруживает — `ping` не получает ответа — и **ставил только
флаг** `connected = False`. Сокет оставался открытым, задача чтения — живой.
3. Цикл переподключения в это время стоял в `asyncio.wait([..., listen_task])` и
ждал завершения задачи чтения, которой не суждено было завершиться. С
следующей итерации heartbeat выходил по `if not connected: continue`, то есть
**выключал себя сам**, опираясь на флаг, который сам же и поставил.

Итог ровно тот, что наблюдался на стенде: обрыв обнаружен и записан в журнал,
`ping failed ... forcing reconnect` встречается в журнале **ровно один раз**, а
дальше — тишина. Помогает только перезапуск контейнера.

**Починка.** Ветка «ping не ответил» больше не ограничивается флагом: она
закрывает соединение (`_force_disconnect`), а это и есть условие, по которому
цикл замечает обрыв, и отдаёт управление: задача чтения отменяется при
`close()`, `asyncio.wait` возвращается, цикл идёт в переподключение. Тем же
способом переведён и путь «устаревшее соединение» — прежние две строки
(`connected = False` + `close()`) теперь одна, чтобы нельзя было снова
разойтись. Heartbeat после неудачного ping завершает работу, а не крутится
дальше: следующую попытку и новое соединение заведёт уже цикл подключения.

**Заодно устранено одно обещание без действия.** На живом стенде `/ready`
отдавал `ready: true` и «соединение установлено» при отсутствии соединения.
Причина признака та же — он ставился и снимался в разных местах. Теперь при
обрыве он сбрасывается вместе с закрытием сокета, и `/ready` читает правду.

**Проверки (4 штуки, берут настоящий код).** Разрыв сокета без чистого
закрытия приводит к переподключению; мёртвое соединение закрывается, а не
помечается флагом; `/ready` перестаёт сообщать об установленном соединении,
когда сокета нет; во время восстановления `/ready` сообщает об отсутствии
соединения. Каждая падает на прежнем коде: инъекцией возврата старой ветки с
`continue` после установки флага падают 2 проверки из 4 — обе на самом дефекте.
Полный прогон: 2431 passed / 4 failed, mypy strict без ошибок, ruff чист.
Четыре падения — предсуществующие, они зафиксированы ниже как следствие работы
по #77 (`_deployment`), к этой задаче отношения не имеют.

**Чего здесь нельзя доказать.** Живьём на стенде не проверялось: проверка
требует разрыва docker-сети у работающего контейнера с реальным Home Assistant,
то есть действий в чужом доме. Тест воспроизводит тот же класс разрыва —
`recv()`, который не вернётся никогда. Повторить стендовый эксперимент стоит
перед тем, как считать #78 закрытым по-настоящему.

<details>
<summary>Прежний диагноз (2026-10-06, направление оказалось неверным)</summary>

**Наблюдения, из которых выросла задача.**

**Проверено экспериментом, а не чтением кода.** У контейнера платформы была отключена
и затем подключена обратно docker-сеть (`docker network disconnect/connect`). HA при
этом не трогали. Это даёт разрыв сокета без чистого закрытия — тот же класс, что отвал
Wi-Fi или NAT, ради которого написан heartbeat.

**Что сработало.** Обрыв замечен: `ConnectionError: WebSocket connect() succeeded but
connected=False`, запись обрыва, `retrying in 16.0s` — то есть откат 1→2→4→8→16 с
работает и цикл действительно повторяет попытки.

**Что не сработало.** После восстановления сети цикл **завис внутри итерации**:
последняя запись `attempting WebSocket connection (iteration)` в 17:54:04, дальше
ни успеха, ни новой итерации, при том что HA из контейнера доступна за 0.05 с
(проверено `docker exec`), сторож продолжает тикать, а рукопожатий `connection open`
за срок контейнера по-прежнему **одно**. Помощь — перезапуск контейнера: после него
`ready: true`, пять автоматов, соединение поднято.

**То есть #70 закрыл только один из двух путей.** Починен путь «устаревшее
соединение» (тишина, heartbeat сам объявляет обрыв). Путь «настоящая смерть сокета,
переподключение» — не починен: попытка подключения зависает, и цикл больше не
повторяется. Именно ради этого пути heartbeat и написан.

**Отдельно: `/ready` врёт.** Во время зависания он отдавал `ready: true` и
«соединение установлено», хотя соединения не было. Значит готовность считается по
флагу, а не по факту: после обрыва флаг не сбрасывается. Ориентироваться на `/ready`
как на признак живости нельзя — это тот же класс дефекта, что был с ложным обрывом
каждые 5 минут (#76), только с противоположной стороны.

**План, записанный тогда (шаги 1–5).** Выполнено не по этому списку: локализовать
зависание в цикле подключения не потребовалось, потому что виноват был heartbeat
(см. выше). Шаг 4 сделан по существу — признак соединения сбрасывается при обрыве.
Шаги 2, 3 и 5 остаются открытыми и описаны ниже как отдельные пункты.

**Что осталось за рамками починки (не сделано, по записям ниже).**
1. Пределы ожидания на самом подключении: если TCP устанавливается, а рукопожатие
или авторизация не завершаются, нужен таймаут — иначе цикл стоит. В `connect()`
таймауты есть только на двух `recv()` (15 с), на самом рукопожатии нет.
2. Успех подтверждается флагом `connected`, а не подпиской или первым событием.
3. Живая проверка на стенде не выполнена (см. выше).

**Уточнение от 2026-10-06 вечером: где именно зависает.** Добавлена временная
инструментация пути подключения (WARNING вокруг `ClientSession`, `connect()`,
`subscribe()`) и повторён тот же разрыв сети. Результат: **путь подключения
исправен** — `connect()` вернул `connected=True` и `subscribe()` завершился суммарно
за ~170 мс после восстановления сети. Значит зависает **после** `subscribe()`, то
есть либо в коде успеха, либо в `asyncio.wait(...)`. Инструментация откачена.

**Методологическая поправка, важная для следующего разбора.** В этом контейнере
библиотечный DEBUG-журнал WebSocket не выводится вовсе: ноль строк `TEXT`,
ноль `PING`/`PONG`, при том что подключение успешное. Поэтому счётчик
`connection open` здесь **не является признаком переподключения** — я строил на нём
вывод, что рукопожатия не было, и это было недоказуемо. Признак успеха надо искать
по собственным записям адаптера и по живым событиям, а не по журналу библиотеки.

**Номер был занят:** моя находка первоначально шла как #77, но #77 в проекте уже
занят (`SHADOW_MODE` не читается кодом, `DeploymentManager` не подключён). Поэтому
переименовано в **#78**.

**Смежная находка (не моя регрессия):** `tests/test_ha_adapter.py::TestHAAdapterServiceCalls`
— 4 проверки падают с `AttributeError: 'HAAdapter' object has no attribute
'_deployment'`. Проверено: падают и с моими правками, и без них. Причина — работа по
существующему #77: `call_service` теперь обращается к `_deployment` (запрет выхода в
реальный дом), а эти тесты собирают адаптер в обход `__init__`. То есть работа по
#77 доведена до кода, но не до тестов.

**Состояние на момент разбора:** контейнер перезапущен, `ready: true`, пять автоматов,
соединение установлено. Дом работает.

</details>

**Смежное, замечено при разборе, к починке не относится.** `connect()` ждёт два
`recv()` по 15 с, но не ограничивает само рукопожатие, и успех подтверждается
флагом `connected`, а не подпиской или первым событием. Оба пункта остаются
открытыми: они не нужны, чтобы обрыв перестал быть смертельным, но оставляют
окно, где попытка подключения может встать.


### #78 — Переходы по таймауту не переживают перезапуск: автомат застревает включённым (ЗАКРЫТ 2026-10-06)

**Обнаружено:** 2026-10-06, при разборе `history.db` боевого контейнера.

**Суть.** Состояние автоматов восстанавливается из `data/state.json` при старте, а
**отложенный переход по таймауту — нет**. Таймер живёт в памяти процесса, поэтому
после пересоздания контейнера автомат остаётся в состоянии, из которого он должен
был уйти по таймауту, и ждёт триггера, который никогда не придёт.

**Доказательство из боевой базы (`fsm_transitions`, читалось запросом к `history.db`
внутри контейнера).** Реальных переходов за всё время **15** (`reason IS NULL`),
последний — `2026-10-06 13:16:01`, `light.svet_nad_stolom` `OFF → ON_MOTION`.
Дальше за 4 часа ни одного, при том что события продолжали идти: 5529 записей с
причиной `unknown_entity` и 137 с `no_transition`.

Состояние в `state.json` совпадает: `light.svet_nad_stolom_lighting_10` = `ON_MOTION`,
сохранено в 13:16. Контейнер стартовал в 17:01 (`RestartCount: 0`), то есть это не
аварийный перезапуск, а штатный `up -d`.

Сторож это видит и честно сообщает каждую минуту:
`"light.svet_nad_stolom_lighting_10": {"state": "ON_MOTION", "last_transition": null,
"expected_timeout_sec": 30.0, "stuck": true}`, `result: degraded`, `problem_count: 1`.
Действий он не предпринимает — только сигнализирует.

**Почему это не «покрытый случай».** До перезапуска всё работало:
`2026-10-06 09:00:44 OFF → ON_MOTION (motion_detected)`, затем
`09:01:14 ON_MOTION → OFF (timeout)` — ровно через 30 с, как и объявлено в шаблоне
`src/features/lighting.yaml`. Дефект появляется только на стыке «восстановили
состояние — не восстановили таймер».

**Последствие в доме:** свет включается по движению и не гаснет никогда. Для
пробного запуска это блокер.

**Статус:** ✅ исправлено 2026-10-06 по решению владельца, TDD: сначала тесты,
потом код.

**Где именно был разрыв.** `state.json` хранит только `state` и `context` — времени
входа в состояние в нём не было вовсе. Поэтому восстановление получало состояние
без двух необходимых вещей: сколько оно уже пролежало и когда должен произойти
отложенный переход. Таймер при этом подставлялся заново как `loop_time()`, то
есть «сейчас», независимо от реального возраста состояния.

**Починка в трёх шагах.**

1. `StatePersistence.save_state` принимает `entered_at` и кладёт его в запись.
Время настенное (`time.time()`), а не монотонное: монотонные часы цикла после
перезапуска отсчитываются заново от старта процесса и о прошлом не говорят
ничего. Добавлен `load_state_entry` — чтение записи целиком, потому что
`load_state` эту часть отбрасывал.
2. `register_definition` восстанавливает `entered_at` с поправкой на реальный
возраст состояния и **взводит таймер** — раньше он взводился только в пути
перехода, а восстановление шло мимо него.
3. Остаток считается от фактического времени в состояние, а не от старта
контейнера. Иначе починка продлевала бы свечение: состояние, пролежав 25 с
из 30, получало бы ещё 30 вместо оставшихся 5, и с каждым перезапуском
расхождение росло бы. Просроченный таймаут (120 с из 30) срабатывает сразу.

**Про метку из будущего.** Если часы переведены, возраст может выйти отрицательным.
Он обнуляется: иначе таймер оказался бы длиннее объявленного.

**Про состояния, записанные прежней версией.** На существующем томе `state.json`
без `entered_at`. Починка не требует миграции: такое состояние восстанавливается
и получает таймер на полный срок. Компромисс осознанный — остаток неизвестен, но
отказ от запуска хуже.

**Проверки, 10 штук в двух файлах.** `tests/unit/core/test_fsm_timeout_survives_restart.py`
(подставное хранилище) и `tests/contract/test_fsm_timeout_survives_real_restart.py`
(настоящий `StatePersistence` на временном файле). Второй файл существует
отдельно и не напрасно: весь дефект был в том, что **файл** не содержит времени
входа, и заглушка, помнящая `entered_at`, проверяла бы не то, что читает движок
в бою. Проверяется: запись содержит время входа; перезапуск на настоящем файле
возвращает и состояние, и таймер; остаток считается, а не полный срок; просроченный
таймаут срабатывает сразу; состояние без `entered_at` восстанавливается и не
роняет запуск; метка из будущего не даёт отрицательного возраста. Инъекция
прежнего кода роняет 8 проверок из 10.

**Побочно закрыто.** Четыре падения `tests/test_ha_adapter.py::TestHAAdapterServiceCalls`
(`AttributeError: '_deployment'`) — следствие работы по #77: `call_service` стал
обращаться к воротам выхода, а тесты собирали адаптер в обход `__init__`. Падали и
до этой правки. Теперь ворота в заглушках проставлены явно.

**Проверено:** 2445 passed / 0 failed, mypy strict без ошибок, ruff чист,
interrogate 93.0%.

**Не проверено:** живьём в доме. Требуется включить свет по движению, перезапустить
контейнер и убедиться, что свет погас по таймауту сам.

**Смежное, вскрытое при разборе и не входящее в починку.** В шаблоне
`src/features/lighting.yaml` нет перехода по триггеру `motion_cleared` вообще
(есть только `timeout`), поэтому `motion_cleared` даёт 137 отклонений с причиной
`no_transition`. Это ожидаемо по текущему шаблону, но означает, что снятие движения
не выключает свет — выключает только таймаут, а он после перезапуска не работает.


### #79 — Логи в production нечитаемы: 80% объёма — отладочный шум

**Обнаружено:** 2026-10-06, при чтении логов работающего контейнера.

**Факты по фактическому прогону.** `docker logs behavioral-platform | wc -l` = 7716
строк, из них `DEBUG` — 6183 (80%). Основная масса отладочного вывода — бинарный
обмен WebSocket:

```
DEBUG:    > PING b3 d2 62 82 [binary, 4 bytes]
DEBUG:    < PONG b3 d2 62 82 [binary, 4 bytes]
```

Это следствие `LOG_LEVEL=DEBUG` в `deploy/docker/.env`, который к тому же закреплён
ещё в трёх местах (`main.py`, `.env.prod`, compose) — долг D3 в ТЗ F5.

**Вторая половина шума — не следствие уровня логирования.** Синхронизировано
**1489 устройств** против 6 в манифесте, и каждое изменение состояния любой сущности
HA уходит в движок, где отбивается: 654 раза `No FSM definition found for entity ...`
и 692 раза `Publishing event: fsm.rejected`. То есть 97% входящих событий — шум.

**Почему это мешает пробному запуску.** Диагностировать реальный дом нельзя: за час
работы в логе видно несколько значащих строк, а диаграмма состояния (сторож,
переходы, отказы) тонет в `PING/PONG`. При разборе #78 и #77 (SHADOW_MODE) понадобилось читать не
логи, а `history.db` напрямую — то есть обходить собственный инструмент наблюдаемости.

**Статус:** не исправлено. Две отдельные причины, поэтому и два исправления:
уровень логирования в production и сужение набора устройств (почему синхронизировано
1489 сущностей — отдельный вопрос, отдельная задача).


### #80 — Отложенный переход отменялся приходящими событиями: `trigger()` отменял таймер до разбора события; свет не гас даже без перезапуска
- **Статус:** ✅ закрыт 2026-10-07: отмена перенесена на выполненный переход, таймер защищён от самопорождения; проверено в бою


### #81 — Источник HA показывался отключённым при 1502 работающих устройствах: успешная синхронизация не писала `status` и `device_count`
- **Статус:** ✅ закрыт 2026-10-07: статус и счётчик пишутся, отказ честно переводит в `disconnected`, время успешной синхронизации не затирается. Остаток закрыт: `check_source_sync` в `/ready` — периодической синхронизации нет, и теперь об этом сказано


### #82 — Подписка на все 1502 сущности дома без фильтра: каждое событие лишней сущности разбиралось и отбивалось как `unknown_entity`
- **Статус:** ✅ закрыт 2026-10-07: `entity_ids` в `subscribe_events`, список из манифеста (21 сущность); в бою ни одного отказа с момента старта

---

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

## Последние значимые изменения

| Дата | Изменение | Файлы | Статус |
|------|-----------|-------|--------|
| 2026-10-07 | **#82 — платформа больше не подписывается на все 1502 сущности дома.** Найдено при разборе остатка #79. Адаптер подписывался на все `state_changed` **без фильтра**, и каждое изменение состояния любой сущности — `sun.sun`, заряда батареи, питания обогревателя — приходило в платформу и разбиралось. Движок отбивал такое как `unknown_entity`: 7384 отказа за всё время. Замолчание отказов (#79) убрало шум из журнала, но **поток продолжал приходить** — по сети, по разбору, по записи в `history.db` и публикации `fsm.rejected`. Считать 1500 событий в минуту ради шести нужных — работа впустую, растущая вместе с домом. **Починка на стороне сервера, а не фильтром у себя:** WebSocket API Home Assistant принимает в `subscribe_events` поле `entity_ids`, и Home Assistant присылает только их. Список собирается из манифеста (устройства комнат и их датчики) функцией `collect_subscribed_entities` — тем же механизмом, что у `EventRouter`, чтобы подписка и маршрутизация не разошлись. Манифест отдаётся адаптеру через атрибут, а не через `__init__`: он меняется при hot-reload, и копия в адаптере разошлась бы с настоящей. **Пустой манифест означает подписку на всё, а не на ничего** — при пустом списке платформа стала бы молчащей (соединение есть, `/ready` зелёный, событий нет), а это неотличимо от поломки. **Проверено в бою:** `subscribed to state_changed for 21 entities from manifest`; с момента старта контейнера **ни одного отказа** и ни одной записи в `history.db` (последний отказ был за 9 секунд до старта). За 3 минуты в журнале 9 строк против тысяч: только сторож и healthcheck. Сторож `ok`, `problem_count: 0`. Проверок 7, инъекция прежнего кода роняет 5 | `src/adapters/ha_adapter.py`, `src/core/events/event_router.py`, `src/core/container.py`, `tests/unit/adapters/test_ha_subscription_filter.py` | ✅ Исправлено и проверено в бою |
| 2026-10-07 | **#81 — источник Home Assistant показывался отключённым при 1502 работающих устройствах.** Проверено в бою: `sources.json` содержал `status: disconnected`, `device_count: 0`, `last_sync` от 5 октября. Синхронизация при этом работала — по запросу `POST /sync` загрузилось 1502 устройства, и время обновилось до текущего. **Причина:** `_mark_source_synced` обновляла только `last_sync` и `last_error`. Поля `status` и `device_count` после синхронизации не менял никто — grep по `src/` подтверждает: `device_count` в `HASource` есть, но заполнялся только в ответе API, а не в самой модели. **Почему это опаснее, чем выглядит:** статус источника интерфейс берёт из этого поля, то есть показывал «Дом отключён» при исправном источнике — оператор начал бы чинить то, что не сломано. И второе: **периодической синхронизации в проекте нет** — `_mark_source_synced` вызывается только из ручного `POST /sync`. Поэтому «последняя синхронизация от 5 октября» не выглядит поломкой: просто её никто не запускает. **Починка:** успешная синхронизация пишет `status: connected` и фактическое число устройств (канонический статус, а не исторический `active` — API понимал оба, но источник обязан иметь одно); отказ переводит источник в `disconnected`, пишет причину и **не трогает** время последней успешной синхронизации — иначе оператор увидел бы свежую дату при данных трёхдневной давности. Проверок 7, инъекция прежнего кода роняет все 7. **Проверено в бою:** после перезапуска и синхронизации `status: connected`, `device_count: 1502`, `last_sync` текущий, `/api/v1/devices/sources` отдаёт `connected`. **Осталось отдельной задачей:** периодической синхронизации нет как таковой, и `/ready` о ней молчит | `src/services/device_service.py`, `tests/unit/services/test_source_status_after_sync.py` | ✅ Исправлено и проверено в бою |
| 2026-10-07 | **По решению владельца: шум в журнале убран, движение выключает свет, миграции признаны ненужными.** Четыре решения и три следствия. **(1) `SHADOW_MODE=true` оставлен осознанно** — дом настраивается, платформа не должна трогать лампы; режим виден в `/ready`, который отвечает 503 и называет причину. **(2) Добавлен переход `ON_MOTION --[motion_cleared]--> OFF`** в `lighting.yaml`: датчик шлёт `motion_cleared` постоянно, а такого триггера в шаблоне не было, поэтому все события заканчивались `no_transition` и свет гас только по таймауту. `timeout_sec` у перехода намеренно не задан: снятие движения выключает сразу, иначе выключение задержалось бы вторым способом. Контракт регенерирован — `motion_cleared` перешёл из «непокрытых событий платформы» в производимые (`sensor`). **(3) Отказы переходов замолчали по умолчанию:** 1489 синхронизированных сущностей против 6 в манифесте давали по две строки журнала на каждое событие. Теперь первое упоминание сущности пишется, повторы молчат; число строк растёт с числом РАЗЛИЧНЫХ сущностей. Отказ при этом не стал невидимым — он попадает в историю переходов и в `rejection_counts()` по причинам, то есть наблюдаемость переехала туда, где полезна, и по счётчику видно, какие сущности платформа отбивает (это и есть основание сузить набор устройств). Флаг `FSM_LOG_REJECTIONS=1` возвращает прежнее поведение целиком; нераспознанное значение его не включает — опечатка не должна молча возвращать 80% шума. **(4) Бинарный обмен WebSocket убран из журнала:** `websockets` на `LOG_LEVEL=DEBUG` писал `> PING b3 d2 62 82 [binary, 4 bytes]` на каждое сообщение — 80% объёма, из-за чего переходы приходилось искать в `history.db` напрямую. Поднимается уровень конкретных библиотек, а не всех: `sqlalchemy` и прочие на DEBUG дают полезный вывод. Возврат — `FSM_LOG_LIBRARY_DEBUG=1`. **Проверено в бою:** за 5 минут 38 отказов на 38 сущностей (повторов нет), бинарных кадров 0, за 3 минуты ни одного `no_transition`; переход `ON_MOTION → OFF` по `motion_cleared` в 07:27:34 — снятие движения выключило свет без ожидания таймаута; сторож `ok`, `problem_count: 0`. Полный прогон 2466 passed | `src/core/fsm/engine.py`, `src/core/logging_setup.py`, `src/main.py`, `src/features/lighting.yaml`, `src/features/CONTRACT.yaml`, `deploy/docker/.env.example`, `tests/unit/core/test_fsm_rejection_log_bounded.py` | ✅ Проверено в бою |
| 2026-10-07 | **#80 — отложенный переход отменялся приходящими событиями: свет не гас даже без перезапуска. Найдено на стенде при проверке починки #78 в бою, воспроизведено тестом.** Таймер восстановился и был взведён верно (`timer armed for 30.0s`), но через минуту сторож честно сообщил `stuck: true` — переход не наступил. Причина не в починке таймеров, а рядом: `FSMEngine.trigger()` отменял таймеры **первым действием, до разбора события**. Отмена означает «состояние изменилось, прежнее ожидание не действует», но событие может не дать перехода вовсе. В `lighting.yaml` нет перехода по `motion_cleared`, и боевой журнал это показывает прямо — из `ON_MOTION` идут `motion_detected` и `motion_cleared`, все заканчиваются `no_transition`. Датчик в жилой комнате шлёт события каждые 15–60 с: каждое съедало таймер, а новый не взводилось, потому что перехода не было. **То есть свет не гас и в живом процессе — дефект не был связан с перезапуском, и прежняя починка его не покрывала.** **Вторая правка, найденная при первой:** обработчик таймаута сам зовёт `trigger`, а тот на выполненном переходе отменяет прежние таймеры — включая тот, который его вызвал. Без защиты таймер отменял сам себя на середине срабатывания. Запись снимается ДО отмены, иначе обработчик, добравшись до конца перехода, записал бы новый таймер, а следующая отмена сняла бы не тот. **Почему не поймали прежние проверки:** они ждали тишины — пока событий нет, таймер живёт и срабатывает. Проверка на тишине доказывает, что таймер работает в покое, и ничего не говорит о том, что происходит, когда события идут. В доме события идут всегда. **Проверено в бою:** пересобран образ, перезапущен контейнер, состояние `ON_MOTION` (с 13:16 вчера) ушло в `OFF` по таймауту через 30 с несмотря на поток событий датчика; сторож впервые за сутки отдаёт `result: ok, problem_count: 0`. Проверок 3, инъекция прежнего кода роняет 2 | `src/core/fsm/engine.py`, `tests/unit/core/test_fsm_timer_survives_noop_event.py` | ✅ Исправлено и проверено в бою |
| 2026-10-07 | **`run_checks.sh` проходит целиком: проверка .gitignore работала против устаревшего эталона, а скрипта проверки не существовало вовсе.** Два дефекта, оба молчаливые. **Первый:** pre-commit звал `.ai/scripts/check_gitignore.sh` под условием `[[ -x ... ]]` — файла не было, условие не выполнялось, проверка пропускалась. То есть `.gitignore` можно было править свободно, хотя правила проекта это запрещают; молчание выглядело как «проверка прошла». **Второй:** эталон `.ai/templates/qwen.gitignore.fix` разошёлся с файлом — коммиты `5dad5f8` и `848b140` добавили правила для ключа шифрования (`encryption.key`) и для `.env.*`, а эталон остался прежним. `run_checks.sh` сравнивал файл с устаревшим эталоном и падал на каждом запуске, предлагая «восстанови .gitignore из шаблона», то есть **откатить правила безопасности** и вернуть в индекс каталоги с манифестом и копиями бэкапов. Обе проверки молчали о разном: одна — о факте правки, вторая сравнивала с неверным эталоном. **Починка:** эталон синхронизирован с фактическим состоянием; создан скрипт проверки, который сверяет файл с эталоном **и** проверяет наличие обязательных правил (`encryption.key`, `.env.*`, `!.env.example`, рабочие каталоги развёртывания) — сверка с эталоном доказывает тождество файлов, но не то, что в эталоне написано правильное, поэтому тот, кто ошибся бы при обновлении эталона, ошибся бы и здесь; pre-commit вызов скрипта сделан обязательным, а не условным. **Проверено прогонами:** штатное состояние — exit 0; дописывание правила ловится; удаление `encryption.key` ловится даже после подгонки эталона под испорченный файл. Полный прогон `run_checks.sh` — **exit 0** (2453 passed, покрытие 93.1%, mypy strict, ruff, interrogate) | `.ai/scripts/check_gitignore.sh`, `.ai/templates/qwen.gitignore.fix`, `.ai/scripts/run_checks.sh`, `.githooks/pre-commit` | ✅ Закрыто |
| 2026-10-06 | **#77 закрыт: режим развёртывания назван в `/ready`, а не только в журнале при старте.** Проводка `DeploymentManager.from_env()` в контейнер уже была сделана в `fa29a87` и проверена на стенде (контейнер печатает `Режим развёртывания: shadow (SHADOW_MODE='true')`), но режим был виден только одной строкой в логе — **зеркальная сторона того же дефекта**: тогда оператор считал систему безопасной, а она трогала дом; теперь платформа может молча блокировать все команды, а оператор видит исправную систему (события приходят, автоматы считают состояния, `ready: true`, лампы не включаются). Добавлена `check_deployment_mode` и включена в `collect_checks`: в режиме тени готовность **ложная** — система принимает события, но не исполняет обещанное, — поэтому `ok: false` плюс название режима и подсказка, как включить выход. 503 на `/ready` не ломает healthcheck: Docker зовёт `/health`, который остаётся всегда 200 (иначе был бы рестарт-цикл). **Дефолт исправлен в документации:** `deploy/README.md` обещал `SHADOW_MODE` по умолчанию `false`, а код при незаданной переменной и при опечатке даёт режим тени — иначе забытая настройка молча включала бы управление реальным домом. **Проверки 8:** режим назван; тени `ok: false`; активному и гибридному `ok: true`; признак совпадает с решением ворот для всех четырёх режимов; отсутствие менеджера и контейнера не ломает готовность; проверка попала в сводку. Инъекция прежнего кода роняет все 8 | `src/webui/routes/readiness.py`, `tests/unit/webui/test_readiness_deployment_mode.py`, `tests/unit/webui/test_readiness_checks.py`, `deploy/README.md` | ✅ Код и тесты |
| 2026-10-06 | **#78 (таймаут-переходы) закрыт: свет больше не застревает включённым после перезапуска.** `state.json` хранил только `state` и `context` — времени входа в состояние не было вовсе, поэтому восстановление получало состояние без двух нужных вещей: сколько оно пролежало и когда должен произойти отложенный переход. Таймер при этом подставлялся заново как `loop_time()`, то есть «сейчас». **Починка:** `save_state` принимает `entered_at` (настенное время — монотонные часы цикла после перезапуска отсчитываются заново и о прошлом не говорят ничего) и кладёт его в запись; добавлен `load_state_entry`, потому что `load_state` эту часть отбрасывал; `register_definition` восстанавливает `entered_at` с поправкой на реальный возраст и **взводит таймер** — раньше он взводился только в пути перехода, а восстановление шло мимо. **Остаток, а не полный срок:** иначе починка продлевала бы свечение (пролежал 25 с из 30 → получил бы ещё 30, и с каждым перезапуском расхождение росло бы). Просроченный таймаут срабатывает сразу; метка из будущего обнуляется. Миграция не требуется: состояния без `entered_at` восстанавливаются и получают таймер на полный срок — осознанный компромисс, отказ от запуска хуже. **Проверки 10 в двух файлах:** подставное хранилище и настоящий `StatePersistence` на временном файле. Второй файл не напрасен — весь дефект был в том, что **файл** не содержит времени входа, и заглушка, помнящая `entered_at`, проверяла бы не то, что читает движок в бою. Инъекция прежнего кода роняет 8 из 10. **Побочно закрыто:** 4 падения `TestHAAdapterServiceCalls` (`AttributeError: '_deployment'`) — следствие #77, падали и до этой правки. **Не проверено живьём:** включить свет по движению, перезапустить контейнер, убедиться что погас сам | `src/core/fsm/engine.py`, `src/core/persistence/state_persistence.py`, `tests/unit/core/test_fsm_timeout_survives_restart.py`, `tests/contract/test_fsm_timeout_survives_real_restart.py`, `tests/test_hot_reload_memory.py`, `tests/test_ha_adapter.py` | ✅ Код и тесты |
| 2026-10-06 | **#78 закрыт: heartbeat находил настоящий обрыв сети, но переподключения не происходило.** Диагноз, записанный вчера, вёл в цикл подключения; виноват оказался heartbeat — механизм, написанный именно для этого обрыва. Разрыв без чистого закрытия (отвал Wi-Fi, `docker network disconnect`) не завершает задачу чтения: `recv()` ждёт данных, которых не придёт. Heartbeat обнаруживал это по неудачному `ping`, но **ставил только флаг** `connected = False` — сокет оставался открытым, задача чтения живой. Цикл стоял в `asyncio.wait` и ждал завершения задачи, которая не завершится никогда, а heartbeat со следующей итерации выходил по `if not connected: continue` и **выключал себя сам**, опираясь на флаг, который сам же поставил. Отсюда картина стенда: `ping failed ... forcing reconnect` в журнале ровно один раз, дальше тишина, спасает перезапуск. **Починка:** неудачный ping закрывает соединение (`_force_disconnect`) — это и есть условие, по которому цикл замечает обрыв; тем же переведён путь «устаревшее соединение», чтобы две строки снова не разошлись. Heartbeat после неудачи завершает работу: следующую попытку заведёт цикл подключения. **Побочно устранено обещание без действия:** `/ready` больше не отдаёт `ready: true` при отсутствии соединения. **Инъекция:** возврат прежней ветки (`continue` после установки флага) роняет 2 проверки из 4 — обе на самом дефекте. **Не проверено:** живьём на стенде (нужен разрыв docker-сети у контейнера с реальным HA). **Открыто:** предел ожидания на рукопожатии и подтверждение успеха подпиской, а не флагом | `src/adapters/ha_adapter.py`, `tests/unit/test_ha_adapter_dead_socket.py`, `tests/unit/test_ha_adapter_ready_truth.py` | ✅ Код и тесты |
| 2026-10-05 | **Сквозная проверка пункта 5 на реальном устройстве — направление «включение» доказано, обратное нашло три дефекта.** Источник: реальный Home Assistant `http://192.168.2.10:8123`, 1490 устройств. Датчик: **управляемый стенд вместо физического** — по решению владельца создан `input_boolean.shp_smoke_test_motion` (служебное имя, иконка `mdi:flask-outline`), потому что адаптер только подписывается на `state_changed` и начального чтения состояний нет: настоящий датчик потребовал бы физического присутствия. Создан **через WebSocket API** — `input_boolean/create`; я ошибочно утверждал, что HA не даёт создавать сущности программно, и был неправ: команда есть в HA 2026.7.2. Формат команды установлен пробой: `name` и `icon` принимаются, `id` — нет; удаление требует ключ `input_boolean_id`, а не `entity_id`. **Помещение:** комната `test_svet` добавлена в манифест **точечной правкой файла**, а не перегенерацией — `yaml.safe_dump` ранее переформатировал манифест и потерял комментарии (оригинал восстановлен по хешу `d5c0f6be…`, 2667 Б). **Проверено запуском, направление «включение»:** `input_boolean.turn_on` → `Routing: sensor=… → fsm=…_lighting_10, event=motion_detected` → `Transition 'OFF' -> 'ON_MOTION'` (guard `make_is_day_time.<locals>.is_day_time`, action `turn_on_light`) → `Publishing event: fsm.transitioned` → лампа загорелась. Вся цепочка живая. **Направление «выключение» не работает**, найдено три независимых дефекта: (#65) устройство, добавленное через `POST /api/v1/devices/apply`, **не сохраняется** — `device_lifecycle.py` не знает про `ManifestStore` (0 ссылок, 0 `.save()`), при этом старый путь `discovery_service.apply_selective` сохраняет; API отвечает 201, устройства нет ни в одной копии манифеста; (#66) таймаутные переходы не срабатывают — 90 с в `ON_MOTION` при `timeout_sec: 30.0`, и **сторож сам это зафиксировал** (`stuck: true`, `degraded`), то есть детектор исправен, исполнитель — нет; (#67) платформа публикует `motion_cleared`, шаблон `lighting` такого триггера не знает. **Побочно подтверждено:** сторож очереди 6 ловит реальный дефект, а не только синтетику; диагностический эндпоинт — `/api/fsm/state` (не `/api/v1/fsm/devices`, которого не существует). **Состояние возвращено:** лампа `on` как была, датчик `off`, артефакты оставлены по решению владельца. По FR-026 дефекты **зафиксированы, а не исправлены** | `.ai/01_PROJECT_STATE.md` (Known Issues #65–#67), `deploy/docker/config/manifest.yaml` | ⚠️ Пункт 5 выполнен наполовину ||
| 2026-10-03 | **Волна 0 фичи Verified Coverage (T004–T005):** создана инфраструктура тестов — `tests/helpers/ha_stub.py` перехватывает обращение к внешней системе **на шве установки соединения**, а не на выдаче устройств (подмена выдачи не мешает коду дойти до `connect_to_ha`, из-за чего текущий падающий тест уходил на `192.168.1.100:8123`); `tests/integration/conftest.py` даёт идентичность из подготовки и изолирует персистентность во временном каталоге. **Дефект, вскрытый самопроверкой:** функции-заглушки были объявлены без аргументов и подставлялись на методы с `self` — `patch(..., new=функция)` не превращает функцию в дескриптор, поэтому 10 из 17 тестов падали `TypeError: takes 0 positional arguments but 1 was given`. Исправлено принятием `*args`. **Побочно зафиксировано:** режимы отказа внешней системы неразличимы на уровне HTTP API, потому что `connect_to_ha` гасит любое исключение и возвращает `False`; различение возможно только на уровне клиента, и тесты не делают вид, будто различают. **Проверено:** 17/17 новых тестов; полный прогон 1794 passed / 9 skipped / 0 failed (+17); `tests/integration/` без регрессий; вклад новых тестов в `data/sources.json` — **0 байт** (контрольный прогон дал те же +17 123 байта, что и без нового файла) | `tests/helpers/ha_stub.py`, `tests/integration/conftest.py`, `tests/integration/test_fixtures_infrastructure.py` | ✅ Complete (волна 0) |
| 2026-10-03 | **Чистка байткода и мёртвой фикстуры (BACKLOG B10, B11):** из индекса git убраны 117 отслеживаемых `.pyc` — правило `__pycache__/` уже было в `.gitignore` и работало, файлы были отслеживаемы до его добавления, поэтому правка правил не потребовалась. Удалена автофикстура `tests/conftest.py::webui_server`: `autouse=True`, но не запрошена ни одним тестом, поднимала процесс на ASGI-цели `src.webui.app:app`, которой в модуле нет (модульный `app` объявлен только в `src/main.py`) — процесс всегда падал с кодом 3, а ожидание порта занимало до 15 секунд. Попутно починены таргеты `make run-webui` и `make run-webui-prod` с той же битой целью: переведены на фабрику `src.webui.app:create_app --factory`, проверено запуском (`/health` отвечает, ошибки загрузки ASGI нет). **Проверено:** 1777 passed / 9 skipped / 0 failed | `tests/conftest.py`, `Makefile`, `.ai/BACKLOG.md` | ✅ Complete |
| 2026-10-02 | **Baseline перед F3 (наблюдаемость) зафиксирован:** `pytest tests/` = **1725 passed / 9 skipped / 0 failed** (совпадает с итогом F2), покрытие 78%; `.ai/scripts/run_checks.sh` = **exit 0** (93.4% покрытие, mypy --strict без ошибок, ruff, interrogate); `tests/test_webui_playwright.py` — 23 passed / 2 предсуществующих падения (Known Issue #15). **Волна 0 завершена (10/43 задач):** сборщик показателей получил изолируемый реестр измерений и научился деградировать вместо падения при сбое регистрации, ограничено число серий метрики переходов, добавлены счётчики отказов и восстановлений состояний, движок отдаёт `expected_timeout_sec()`, настройки наблюдаемости читаются из окружения | `src/core/metrics.py`, `src/core/fsm/engine.py`, `src/services/watchdog.py`, `tests/test_metrics.py`, `tests/unit/core/test_fsm_engine_timeouts.py`, `tests/unit/services/test_watchdog_settings.py` | В работе (волна 0) |
| 2026-10-01 | F2 US4 завершена (60/71 задач, T051–T060) — визуализации показывают фактические данные. **Код:** `src/core/persistence/event_store.py` — агрегация `get_activity_heatmap()` (по дням недели и часам из таблиц переходов и событий) и `get_hourly_history()` (по настенным часам суток), обе возвращают явный `has_data`; `src/services/fsm_state_bridge.py` — подписка на канал `state_change` и запись событий устройств в журнал; `src/webui/routes/__init__.py` — карта активности и история событий переведены на агрегацию журнала, **подсказки возвращаются объектом `{suggestions, has_data}`**, удалены три выдуманные записи, убран лишний аргумент `responded_at`, из-за которого ответ на подсказку был 500; `src/webui/templates/dashboard.html` — вместо пустых графиков и списков показывается сообщение «Данных пока нет». **Исправлена предсуществующая ошибка mypy** в этом же разделе: корзины истории считались «часов назад» при подписях от `00:00`, из-за чего график отображался задом наперёд; now считается по настенным часам, `mypy src/ --strict` — **0 ошибок по всему проекту**. **Проверено:** 1703 passed / 9 skipped / 0 failed (+14), Playwright: 4 новых E2E проходят; вживую: на пустой системе все три раздела отдают `has_data: false` без выдуманных значений, после записей суммы на графиках точно равны числу записей (4), событие легло в корзину своего часа (19:00 → 2 записи), повторные запросы идентичны | `src/core/persistence/event_store.py`, `src/services/fsm_state_bridge.py`, `src/webui/routes/__init__.py`, `src/webui/templates/dashboard.html`, `tests/integration/test_fsm_history_sections.py`, `tests/test_webui.py`, `tests/test_webui_playwright.py` | ✅ Complete (US4) |
| 2026-10-01 | F2 US3 завершена (50/71 задач, T037–T050) — интерфейс показывает состояние в реальном времени. **Код:** `src/webui/routes/devices/websocket.py` — `build_fsm_transition_message()`, `make_fsm_broadcaster()`, `resolve_device_uuid()`: событие перехода приходит с `entity_id` Home Assistant, а подписки — по UUID, поэтому добавлено разрешение имён; `src/webui/app.py` — раздатчик подключается к мосту состояний (`app.state.fsm_broadcaster`), `/ws/live` с мёртвым менеджером и анонимной раздачей **удалён** (его заменил канал устройств с проверкой прав); `src/main.py` — импорт `webui.app` заменён на канонический `src.webui.app`; `src/webui/routes/__init__.py` — диаграмма отдаётся чистой Mermaid-строкой; `templates/index.html` — живой канал устройств с авторизацией и подпиской, состояния на карточках сразу при загрузке, индикатор «Нет обновлений» при обрыве, подсветка текущего состояния в окне схемы; `templates/dashboard.html` — убран вписанный «Active», состояния из раздела автоматов, схемы читаются как текст. **Три настоящих дефекта найдены E2E-тестами и исправлены:** (1) **двойная загрузка модулей** `webui.*` и `src.webui.*` давала два независимых `connection_manager` — раздача живых обновлений уходила «в никуда»; путь импорта унифицирован с `Makefile`; (2) **генератор диаграмм выдавал неразбираемый Mermaid** (`машина : СОСТОЯНИЕ`) — интерфейс показывал ошибку парсинга вместо схемы; теперь каждое состояние объявляется как `state "Имя" as идентификатор`, параллельные дублирующиеся рёбра объединяются в одно (иначе разметка падала с «Could not find a suitable point»); (3) **диаграмма рисовалась в скрытом модальном окне** — Mermaid не может вычислить разметку при нулевой ширине, отрисовка перенесена на событие `shown.bs.modal`. **Проверено:** 1689 passed / 9 skipped / 0 failed (+19), отдельный прогон Playwright: 7 новых E2E проходят; вживую: индикатор «Обновления в реальном времени», 8 состояний на карточках сразу при загрузке, схема отрисовывается, текущее состояние видно в модалке, JS-ошибок 0 | `src/webui/routes/devices/websocket.py`, `src/webui/app.py`, `src/main.py`, `src/webui/routes/__init__.py`, `src/webui/templates/{index,dashboard}.html`, `tests/integration/test_fsm_live_updates.py`, `tests/contract/test_fsm_diagram_contract.py`, `tests/test_webui.py`, `tests/test_webui_specification.py`, `tests/test_webui_playwright.py`, `tests/integration/{test_access_control,test_device_audit_log}.py` | ✅ Complete (US3) |
| 2026-10-01 | F2 US2 завершена (36/71 задач, T029–T036) — состояние автоматов доступно по запросу, `since` — реальное время перехода. **Код:** `src/webui/models.py` — `FSMStateView`, `AutomationInfo`, `build_fsm_state_view()`, `build_all_fsm_state_views()`, `build_automation_info()`; `src/webui/routes/__init__.py` — `GET /api/fsm/state` (состояние на момент запроса, `503` с причиной при недоступности движка, пустой список при отсутствии автоматов, фильтрация по существующей модели доступа); `src/webui/routes/devices/devices.py` — поля `fsm` и `automation` в ответе устройства; `src/core/fsm/engine.py` — таблица настенного времени перехода `_last_transition_wall` с публичными `note_transition()`/`get_last_transition_time()`, очистка при снятии автомата. **Две ошибки найдены и исправлены при приёмке:** (1) пустой набор доступных устройств трактовался как «без фильтрации», из-за чего пользователь без прав получал состояния всех устройств — утечка; теперь `None` = фильтрация отключена (админ, недоступный сервис), пустое множество = нет доступа, раздел пуст (регресс-тест в контракте); (2) `since` вычислялся как время чтения ответа, а не время перехода — теперь берётся из движка и не меняется при повторных чтениях. **Проверено:** 1670 passed / 9 skipped / 0 failed (+34), ruff ✅, mypy без новых ошибок; вживую без HA: `since` = `None` до перехода → `2026-10-01T10:55:42.921824` после, повторное чтение не меняет значение, пользователь без прав получает `{"count": 0, "states": []}` | `src/webui/models.py`, `src/webui/routes/__init__.py`, `src/webui/routes/devices/devices.py`, `src/core/fsm/engine.py`, `tests/contract/test_fsm_live_contract.py`, `tests/unit/webui/test_fsm_state_api.py`, `tests/unit/core/test_fsm_event_publication.py`, `specs/007-fsm-live-status/contracts/fsm-live-api.md` | ✅ Complete (US2) |
| 2026-10-01 | F2 US2 завершена (36/71 задач, T029–T036) — состояние автоматов доступно по запросу. **Код:** `src/webui/models.py` — `FSMStateView` (контрактные поля `fsm_id`, `device_id`, `behavior`, `state`, `since`, `automated`), `AutomationInfo` (явная отметка `no_automation`), сборщики представлений из движка с фильтрацией по устройствам и преобразованием монотонного `entered_at` в настенное ISO-8601 (внутренний `context` наружу не отдаётся); `src/webui/routes/__init__.py` — `GET /api/fsm/state`: состояние на момент запроса без кэша, `503` с причиной при недоступности движка (не пустой список!), пустой список при отсутствии автоматов, фильтрация по существующей модели доступа с откатом на «без фильтрации» при сбое сервиса устройств; `src/webui/routes/devices/devices.py` — поля `fsm` и `automation` в ответе устройства (форма `automation` единая: ключи присутствуют всегда). **Проверено:** 1656 passed / 9 skipped / 0 failed (+20), ruff ✅, существующие контракты устройств (154 contract+integration) без правок; вживую без HA: `GET /api/fsm/state` → 200, 8 автоматов с корректными полями, после перехода состояние совпадает с фактическим (`OFF` → `ON_MOTION`, SC-004), при недоступном контейнере → `503` с описанием, а не пустой список | `src/webui/models.py`, `src/webui/routes/__init__.py`, `src/webui/routes/devices/devices.py`, `tests/contract/test_fsm_live_contract.py`, `tests/unit/webui/test_fsm_state_api.py`, `specs/007-fsm-live-status/contracts/fsm-live-api.md` | ✅ Complete (US2) |
| 2026-10-01 | F2 US1 завершена (28/71 задач, T015–T028) — переходы автоматов доходят до подписчиков, состояния переживают перезапуск. **Код:** `src/core/events/fsm_events.py` (новый — имена событий `fsm.transitioned`/`fsm.rejected`/`platform.started`, 5 причин отказа, префиксы `manual_*`, единый ISO-8601, сборка payload с валидацией обязательных полей, разбор идентификатора `{устройство}_{шаблон}_{приоритет}`); `src/services/fsm_state_bridge.py` (новый — подписка на оба события, зеркало состояния в HA через существующий диспетчер `input_text.set_value` с низким приоритетом, запись в журнал переходов, живая рассылка; каждое действие изолировано и не влияет на переход); `core/fsm/engine.py` (публикация в 5 точек отказа + после записи состояния, неблокирующая доставка с отслеживанием задач и гашением в `shutdown()`, хелпер `loop_time()`); `core/container.py` (движок получает шину и `StatePersistence`, диспетчер связывается после сборки, `announce_started()`, мост в `PlatformContext`); `core/persistence/state_persistence.py` (путь `data/state.json`); `core/persistence/event_store.py` (аддитивная миграция колонок `success`/`reason`, чтение их в `get_recent_transitions`); `core/fsm/persistence.py` и `core/persistence/context_manager.py` (подписка на `fsm.transitioned`, синхронные обработчики больше не логируют ложную ошибку); `core/events/event_bus.py` (синхронные подписчики, устранён двойной вызов при `TypeError` из тела); `services/device_service.py` (`subscribe_state_changes()` — обработчик изменения состояния больше не висит без подписки, ровно одна подписка); `webui/app.py` (одна шина вместо второй пустой, вызов подписки); `main.py` (`await container.announce_started()`). **Проверено:** 1636 passed / 9 skipped / 0 failed (+41), ruff ✅, mypy --strict без новых ошибок; вживую без HA: переход OFF→ON_MOTION публикуется со всеми полями и тем же `trace_id`, попадает в журнал, состояние **восстанавливается после перезапуска** (SC-016), отказы публикуются с причиной (`no_transition`), файл состояний создаётся в `data/` | `src/core/events/fsm_events.py`, `src/services/fsm_state_bridge.py`, `src/core/fsm/engine.py`, `src/core/container.py`, `src/core/events/event_bus.py`, `src/core/persistence/{state_persistence,event_store}.py`, `src/core/fsm/persistence.py`, `src/core/persistence/context_manager.py`, `src/services/device_service.py`, `src/webui/app.py`, `src/main.py`, `tests/unit/core/{test_fsm_state_persistence,test_fsm_event_publication,test_fsm_publish_non_blocking,test_event_bus_sync_handlers}.py`, `tests/unit/{test_fsm_state_bridge,test_fsm_persistence_subscribers}.py`, `tests/integration/test_fsm_state_persistence.py`, `tests/test_container.py`, `tests/test_state_persistence.py`, `tests/test_fsm_persistence.py`, `tests/test_context_manager.py` | ✅ Complete (US1) |
| 2026-10-01 | F2 Live FSM Statuses: сгенерирован `tasks.md` — **71 задача в 7 фазах** (Setup 3, Foundational 11, US1 14, US2 8, US3 14, US4 10, Polish 11), 34 задачи помечены параллельными, ID последовательны без дублей, каждая задача содержит путь к файлу, формат `- [ ] TNNN [P] [USn]` соблюдён для всех 71. Порядок: Foundational (волна 0) блокирует все истории; US1 (P1) = MVP; US2 (P1) после US1; US3 (P2) после US1+US2; US4 (P3) после US1 и **параллельна US3**. TDD соблюдён: тестовые задачи идут первыми в каждой фазе, в Foundational и US1 — параллельно ([P]); именование `test_<что>_should_<поведение>_when_<условие>`. Три дефекта вне буквального объёма спеки закрываются задачами T013/T014/T027 (диспетчер и хранилище движка) и T022 (зеркалирование через диспетчер вместо несуществующего `adapter.set_entity_state`). Ограничения из data-model процитированы в задачах дословно (набор причин отказа, обязательность `fsm_id`/`to_state`/`reason`, форма `has_data`). В Polish заведены Known Issues дефектов, сознательно оставленных вне объёма (реестр гвардов, недостижимый `MANUAL_SOURCES`, непубликуемое `ha.state_changed`, метрики, префикс-коллизия hot-reload) | `specs/007-fsm-live-status/tasks.md`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete |
| 2026-10-01 | F2 Live FSM Statuses: готов **план реализации** — Constitution Check PASS по всем принципам (I…VII, ADR-001…005), 6 волн: 0) фундамент — инъекция зависимостей движка, публикация перехода, время, неблокирующая шина; 1) US1 — сохранение состояний, единая шина, подписки; 2) US2 — состояния по запросу; 3) US3 — живой интерфейс; 4) US4 — честные данные; 5) полировка. **Три блокирующих дефекта, найденных при исследовании кода, включены в объём фичи:** (1) `Container.fsm = FSMEngine()` (`container.py:130`) без `command_dispatcher` → `CommandIntent` из действий отбрасываются (`engine.py:324-328`), автоматика меняет состояние FSM, но **не отправляет команды устройствам**; (2) тот же конструктор без `persistence` → `save_state`/`load_state` мертвы, состояние не переживает перезапуск; (3) `FSMPersistence._save_state` вызывает несуществующий `adapter.set_entity_state` (`core/fsm/persistence.py:180`). **Исследование (11 решений):** точка публикации — после записи состояния (успех) и в точке отказа (5 причин); источник перехода — по префиксу имени события `manual_*`, т.к. в движке признака источника нет вообще, а `Transition.priority` движком не читается; `State.entered_at` — монотонные часы цикла, поэтому публикуется настенное ISO-8601 (единый формат с событиями `device.*`); `EventBus.publish` последователен и блокирует, а его запасной путь ломает sync-подписчики (побочные эффекты есть, но каждая доставка логирует ложную ошибку) — доставка перехода делается неблокирующей, `EventBus` чинится без изменения порядка для существующих подписчиков; источник истины состояний — `StatePersistence` (уже встроена в движок, работает в обоих режимах), зеркало в HA — через существующий диспетчер, а не через новый метод адаптера; база живых обновлений — **существующий** канал `/api/v1/ws/devices` (умеет идентичность, подписки, проверку прав при каждой доставке), `/ws/live` выводится из эксплуатации; диаграмма отдаётся чистой Mermaid-строкой, подсветка состояния — на клиенте; графики строятся на `EventStore` (таблицы `fsm_transitions` и `events` существуют, **писателей в `src/` нет ни одного**), попутно исправляется перепутанная ось времени графика событий. **Зафиксировано как вне объёма:** реестр гвардов движка (мёртвый код), `MANUAL_SOURCES` в middleware (требует пересмотра приоритетов), `ContextManager` и непубликуемое `ha.state_changed`, метрики (F3), префикс-коллизия в hot-reload. Риски: 6 позиций с mitigation; главный — оживление мёртвой ветки `ha_adapter.py:309` после появления `event_bus` у движка меняет маршрутизацию состояний (это исправление Known Issue #9, проверяется тестом и вживую) | `specs/007-fsm-live-status/{plan,research,data-model,quickstart}.md`, `specs/007-fsm-live-status/contracts/{fsm-events,fsm-live-api}.md`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete (план) |
| 2026-10-01 | F2 Live FSM Statuses: создана спека `specs/007-fsm-live-status/` — 4 user stories (источник событий P1, запрос состояния P1, живой интерфейс P2, честные данные P3), 39 FR, 17 SC, 22 краевых случая, 6 зависимостей; все 11 наблюдений по проблеме подтверждены кодом. **Дополнительно найдено сверх исходного описания фичи:** (1) `FSMPersistence` (`core/fsm/persistence.py:57`) подписан на `fsm.transition`, который никогда не публикуется → состояние автоматов фактически не сохраняется между перезапусками (в HA-режиме атрибут `{entity}_mode`), т.е. публикация переходов «оживит» эту запись — включено в объём фичи; (2) `src/dashboard/dashboard.py:41` подписан на непубликуемое `fsm.state.changed`; (3) подсветка текущего состояния на диаграмме (`generate_with_highlight`, enhancement 26) в проекте вообще отсутствует; (4) диаграмма отдаётся JSON-конвертом (`webui/routes/__init__.py:155`), а вставляется в страницу как текст (`dashboard.html:242`) — на страницу попадает JSON; (5) третий раздел с mock-данными — `/api/ai/suggestions` (помимо heatmap и истории событий). **Решения пользователя:** D-1 — восстановление состояний автоматов включается в фичу и покрывается тестами (SC-016/SC-017); D-2 — демонстрационные данные визуализаций удаляются полностью (пустой раздел → «данных нет»). Чек-лист качества 20/20, маркеров NEEDS CLARIFICATION не осталось. FR-013 (гарантии доставки подписчикам) сознательно вынесен на этап планирования с явным критерием приёмки SC-015 | `specs/007-fsm-live-status/spec.md`, `specs/007-fsm-live-status/checklists/requirements.md`, `.specify/feature.json`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete (спека) |
| 2026-10-01 | F1 завершена полностью (47/47 задач, T012–T013 и T042–T047). **T012–T013:** контрактные тесты источников и интеграционные тесты сквозного пути закрывают US1. **T042–T043:** quickstart-сценарии 1–6 и 9 прогнаны на живой платформе без Home Assistant (`PYTHONPATH=src CONFIG_PATH=<копия> python3 -m src.main`): добавление видно сразу, повторное применение идемпотентно (`added=0/updated=1`), недоступный источник → 500 с причиной в `last_error` при сохранённых данных, удаление 204 (повторно тоже 204), устройства нет в ответе (404) и в манифесте, `/health` 200 до и после рестарта, удалённые после рестарта не возвращаются, **Traceback в журналах — 0**; единственный 5xx — ожидаемый 500 синка недоступного источника. Результаты зафиксированы в `specs/006-device-lifecycle/quickstart.md`. **T044:** покрытие поднято: `manifest_store` 80→96%, `routes_discovery` 49→95%, `discovery_service` 68→91%, `device_service` 83→93%, `event_router` 95% (цель выполнена), `device_lifecycle` 93%. Найден и исправлен баг: в `dry_run` выборочного применения логика «будет добавлено» была инвертирована. **T046:** в затронутых файлах нет bare `except` и неиспользуемых импортов; `sync_devices_from_source` (69→36 строк кода) и `apply_selective` (63→35) разбиты на helpers. **T047:** 1559 passed / 9 skipped / 0 failed, mypy --strict ✅, run_checks exit 0 | `src/services/device_service.py`, `src/core/discovery/discovery_service.py`, `tests/unit/test_device_service_helpers.py`, `tests/unit/test_device_sync_failures.py`, `tests/integration/test_discovery_routes.py`, `specs/006-device-lifecycle/quickstart.md` | ✅ Complete (F1) |
| 2026-10-01 | F1 US4 завершён (39/47 задач, T037–T041): удаление устройства полное и безопасное. **Код:** `DeviceLifecycleService.delete_device` — каскад: снятие машин состояний → отзыв всех записей о доступе (`delete_accesses_for_device`) → удаление из хранилища, кэша и индексов (`DeviceService.remove_device`) → удаление из манифеста (комната сохраняется, датчик-ссылка тоже вычищается) → перестроение маршрутизации → аудит `device_deleted`; идемпотентно. `DeviceService` помнит удалённые идентификаторы (tombstone), поэтому повторный DELETE — 204, а неизвестный id — 404 (раньше они не различались). Добавлен `DELETE /api/v1/devices/{device_id}` (роль администратора, 204 без тела, 409 при невозможности, 503 без сервиса) и UI-действие в `room_card.html` + `POST /devices/{room}/{entity}/delete` в `app.py` (с `hx-confirm`, передачей пользователя и аудитом). **Проверено:** 1516 passed / 9 skipped / 0 failed (+20), mypy --strict ✅; вживую: DELETE 204 → устройства нет в списке и ответе (404), автоматика снята, права отозваны, запись из манифеста удалена; повторный DELETE 204, неизвестный 404; UI-путь удаляет устройство и обновляет карточку комнаты | `src/services/device_lifecycle.py`, `src/services/device_service.py`, `src/webui/routes/devices/devices.py`, `src/webui/app.py`, `src/webui/templates/partials/room_card.html`, `tests/contract/test_devices_api.py`, `tests/unit/{test_device_lifecycle,test_discovery_page}.py` | ✅ Complete (US4) |
| 2026-10-01 | F1 US3 завершён (34/47 задач, T033–T036): синк источника и список устройств дают одну картину. **Код:** `sync_devices_from_source` больше не создаёт дубли — состояния Home Assistant сводятся с единым хранилищем по паре (источник, `ha_entity_id`): существующие записи обновляются на месте (сохраняются id и выданные права), новые получают права владельца (`grant_access`), иначе они не попадали бы в список вообще; исчезнувшие помечаются `removed_from_ha` и публикуется событие `device.removed`; их машины состояний снимаются через `FSMEngine.unregister` + перестройка маршрутизатора (`DeviceService` получил необязательные `engine`/`event_router`); при повторном появлении статус восстанавливается; ошибка подключения по-прежнему не трогает ранее загруженные устройства, а сохраняется в `last_error` и очищается при успешной синхронизации (FR-015–FR-017). **Проверено:** 1496 passed / 9 skipped / 0 failed (+10), mypy --strict ✅; вживую quickstart 4–5: синк → устройства в списке, три синхронизации → 2 устройства (без дублей), исчезновение → `removed_from_ha` и автоматика снята, сбой подключения → 500 с сохранёнными данными, возврат → `available` | `src/services/device_service.py`, `src/webui/app.py`, `tests/integration/test_device_sync_lifecycle.py`, `tests/unit/test_device_service.py` | ✅ Complete (US3) |
| 2026-10-01 | F1 US2 завершён (30/47 задач, T023–T032): мастер обнаружения переведён на реальные данные. **Код:** `discovery-data` получает устройства и области источника тем же путём, что и синхронизация (`connect_to_ha` → `fetch_devices` → `fetch_areas`), при недоступном источнике отдаёт причину в поле `error`, а не пустой список; `ManifestStore` вынесен из `webui/app.py` в `src/core/persistence/manifest_store.py` (тип модели инъецируется: webui — зеркальная, ядро — каноническая), запись манифеста из `discovery_service` переведена на него вместо сырого YAML, резервная копия теперь содержит состояние ДО мутации (снимок при загрузке), повторное применение не создаёт дублей, занятый слот датчика не перетирается, мёртвый `_hot_reload_fsm` удалён; `discovery.html` переписан (1758 → 727 строк): один блок скриптов вместо двух (второй был вне `<script>`, 540 строк мёртвого JS), дубли идентификаторов разметки устранены, htmx убран, добавлена форма создания источника с ошибками по полям и автовыбором созданного источника, идентичность берётся из серверных атрибутов `data-user-id`/`data-user-is-admin` и подставляется во все запросы `/api/**` (были 401), `/api/rooms` отдаёт комнаты из хранилища манифеста, категории и шаблоны берутся у бэкенда (были несуществующие `switch_control`/`sensor_monitoring`), значения источника экранируются, кнопки блокируются на время применения, причина недоступности источника показывается отдельно от пустого результата. **Проверено:** 1486 passed / 9 skipped / 0 failed (+26), mypy --strict ✓; вживую: мастер отдаёт реальные устройства с областями, создание источника → автовыбор, применение → устройство в списке и работает без перезапуска, без идентичности discovery-data → 401 (тот самый баг) | `src/core/persistence/manifest_store.py`, `src/core/discovery/discovery_service.py`, `src/webui/routes_discovery.py`, `src/webui/routes/devices/sources.py`, `src/webui/templates/{discovery,index}.html`, `src/webui/app.py`, `tests/integration/test_discovery_apply.py`, `tests/unit/{test_discovery_page,test_discovery_manifest_write}.py`, `tests/contract/test_sources_api.py` | ✅ Complete (US2) |
| 2026-10-01 | F1 US1 завершён (20/47 задач, T019–T022): форма `/devices/save` переведена на сервис жизненного цикла — устройство из интерфейса сразу попадает в единый источник, манифест, получает FSM и карту маршрутизации; добавлен обязательный выбор источника в форме (D-009/FR-007, тест на отказ без источника); веб-представление манифеста синхронизируется с ядерным (`_sync_manifest_store`) — устройство видно на главной сразу; исправлено расхождение зеркальных моделей: webui `manual_lockout_min` допускает None, как ядерная (иначе синхронизация падала на валидации); создан общий `_run_coroutine` для синхронных хендлеров; 22 теста формы обновлены под обязательный источник. Проверено: 1460 passed / 9 skipped / 0 failed, mypy --strict ✓, run_checks exit 0; вживую: форма предлагает источник, сохранение через форму → 200, устройство запущено без перезапуска | `src/webui/app.py`, `src/webui/models.py`, `src/webui/templates/partials/device_form.html`, `tests/test_webui.py`, `tests/test_webui_specification.py` | ✅ Complete (US1) |
| 2026-10-01 | F1 US1 (MVP, specs/006, 16/47 задач): единый источник устройств + транзакция жизненного цикла. **Код:** удалён временный словарь роутов `_devices_store` (2 экземпляра модуля, пустой список после рестарта) — чтение списка/устройства/конфигурации/команд идёт через `DeviceService`; добавлены `get_all_devices`/`list_devices`/`hydrate_from_persistence`/`add_device`/`remove_device` (идемпотентность по `ha_entity_id` + источнику); новый `src/services/device_lifecycle.py` (манифест → хранилище → runtime → FSM → маршрутизация → аудит, компенсация при сбое); `EventRouter.rebuild()`; `EventBus.unsubscribe_with_filter` (отписка от подписок с фильтром); типы событий жизненного цикла; удалён дубль `POST /apply` (реально обрабатывался `get_devices`, 201 + `[]`); `apply_devices` переписан на сервис (dry_run без побочных эффектов, частичный успех); гидратация при старте + идентичность UI по умолчанию из `WEBUI_DEFAULT_USER_ID`/`WEBUI_DEFAULT_USER_ADMIN`; `ha_adapter=None` заменён на общий адаптер. **Проверено:** 1459 passed / 9 skipped / 0 failed (+17), mypy strict ✓, run_checks exit 0; quickstart-сценарии 1–3 вживую: устройство видно сразу без перезапуска, переживает перезапуск, автоматика создаётся и датчик зарегистрирован в карте маршрутизации, повторное применение идемпотентно (added 0/updated 1) | `src/services/device_lifecycle.py`, `src/services/device_service.py`, `src/webui/routes/devices/{devices,deps}.py`, `src/webui/app.py`, `src/core/events/{event_router,event_bus}.py`, `src/core/persistence/manager.py`, `src/core/models/device_sync_event.py`, `tests/helpers/`, 5 новых/правленых тестовых файлов | ✅ Partial (US1) |
| 2026-09-30 | F1 Device Lifecycle: сгенерирован `tasks.md` — 47 задач в 7 фазах (Setup 3, Foundational 8, US1 11, US2 10, US3 4, US4 5, Polish 6), 19 задач помечены как параллельные, ID последовательны без дублей, все задачи содержат путь к файлу; порядок: Foundational блокирует всё, US1 = MVP (добавление+оживление), US2 мастер (после US1), US3 синк↔список (после US1), US4 удаление (после US1), Polish после историй; тестовые задачи идут первыми в каждой истории (TDD, FR-030) | `specs/006-device-lifecycle/tasks.md`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete |
| 2026-09-30 | F1 Device Lifecycle: подготовлен план реализации — research.md (15 решений с обоснованиями: единый хранилище DeviceService+persistence, сервис жизненного цикла как единственная транзакция, точечное создание/снятие FSM только через публичный API движка без правок FSMDefinition/debounce/таймаутов, `EventRouter.rebuild()`, данные мастера через `HARestClient` источника, серверная идентичность UI по умолчанию, отписка от отфильтрованных подписок шины), plan.md (Constitution Check PASS по всем принципам, 4 волны реализации, затронутые файлы), data-model.md (7 сущностей, диаграмма статусов, правила валидации), contracts/ (REST-контракты устройств и мастера), quickstart.md (9 сценариев проверки, 6 из них без Home Assistant); одно утверждение исследования отброшено: `Container.build()` синхронный, а не async | `specs/006-device-lifecycle/{plan,research,data-model,quickstart}.md`, `specs/006-device-lifecycle/contracts/*.md`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete |
| 2026-09-30 | F1 Device Lifecycle: создана спека `specs/006-device-lifecycle/spec.md` — 4 user stories (добавление P1, мастер discovery P1, синк↔список P2, удаление P2), 30 FR, 10 SC, 11 edge cases; все 6 дефектов из BACKLOG подтверждены кодом (дубль `/apply`, 401 без X-User-ID в UI, `discovery-data` вместо `discovery/scan`, `ha_adapter=None`, FSM только в `Container.build()`, два хранилища); чеклист качества 20/20; решения пользователя: единый источник — DeviceService+persistence, US4 включён, удаление устройства в объёме | `specs/006-device-lifecycle/spec.md`, `specs/006-device-lifecycle/checklists/requirements.md`, `.specify/feature.json`, `.ai/BACKLOG.md`, `.ai/01_PROJECT_STATE.md` | ✅ Complete |
| 2026-09-30 | Q6 (BACKLOG): починен отдельный прогон `tests/test_webui_playwright.py` — **14 passed за ~40с** (было 14 failed + зависание). Причины: (1) uvicorn запускался на несуществующей цели `src.webui.app:app` (в модуле нет `app`, только `create_app`) → `ERR_CONNECTION_TIMED_OUT` во всех тестах — добавлена фабрика `tests/e2e_app.py`; (2) `wait_for_load_state("networkidle")` недостижим: страница держит WebSocket `/ws/live` → 30с таймаут на каждый вызов, тесты «висели» — переход на `wait_until="load"` + автоожидание `expect(...)`; (3) гонка с CDN (htmx/Bootstrap) — добавлено ожидание `window.htmx`; (4) JSON-эндпоинты читались через `page.content()` (HTML-обёртка) → `page.request`; (5) `/health` ждал текст "healthy" вместо `{"status":"ok"}`; (6) `/api/templates` возвращает конверт `{templates, count}`, а не список; (7) селекторы уточнены по htmx-атрибутам (`hx-target`/`hx-get`); (8) **изоляция**: приложение работает на временной копии манифеста и во временном CWD → E2E-сохранения не трогают репозиторий; teardown с kill-фолбэком, без осиротевших процессов. Основной прогон без изменений: 1411 passed / 9 skipped / 0 failed; `run_checks.sh` exit 0 | `tests/test_webui_playwright.py`, `tests/e2e_app.py` | ✅ Complete |
| 2026-09-30 | Q4 (BACKLOG): устранены все 29 baseline-падений — **полный прогон 1411 passed / 9 skipped / 0 failed** (было 29/1382/9), `run_checks.sh` exit 0. Код: порядок роутеров (sources перед devices — `GET /devices/sources` больше не перехватывается `/{device_id}` → 422), `_call_ha_service` (bool от HAAdapter больше не ломает `CommandExecutionResponse`), `IndexManager.update_device` (алиасинг → чистка по id из всех бакетов), модели (`min_length`/`le` больше не глушат кастомные сообщения валидаторов, `created_at` → `default_factory`), классификатор (`_searchable_text`: `\b` против `_`-сепараторов, `temperatura`, `vent`), sources API (`rstrip("/")` в URL, статус нового источника `disconnected`). Тесты: единый модуль `_devices_store`, мок HA для sync-контракта, конфигурация websocket-моков, `model_dump()` вместо `in` по модели, HA-envelope для `state_changed`, device-blind grant (specs/004), валидные `ha_entity_id`, LRU/батчер-фикстуры | `src/webui/app.py`, `src/webui/routes/devices/sources.py`, `src/services/device_service.py`, `src/core/persistence/index_manager.py`, `src/core/models/{device_config,device_command}.py`, `src/core/discovery/classifier.py`, `tests/contract/{test_devices_api,test_sources_api,test_websocket}.py`, `tests/integration/{test_commands,test_state_sync,test_device_config}.py`, `tests/unit/{test_cache,test_device_service}.py`, `tests/test_websocket_batcher.py` | ✅ Complete |
| 2026-09-30 | Q7 (BACKLOG): `MockAdapter.start()/stop()` — async no-op с флагом `_started` (идемпотентны, `stop()` безопасен без start) → `run_platform()` работает в mock-режиме без `HA_TOKEN`; +8 тестов (lifecycle, idempotency, restart, `PlatformContext.shutdown()` без `HA_TOKEN` ×2); smoke: `python -m src.main` без `HA_TOKEN` → `/health` = `{"status":"ok"}`, 0 Traceback; Known Issue #14 закрыт; полный прогон 29 failed (baseline) / 1382 passed (+8) | `src/adapters/mock_adapter.py`, `tests/test_mock_adapter.py` | ✅ Complete |
| 2026-09-30 | Q3 (BACKLOG): ConfigWatcher подключён к `run_platform()` под env-флагом `HOT_RELOAD` (default OFF): явная сборка Container в main (PlatformContext без контейнера), старт после bootstrap + остановка в `finally`; фиксы: `stop()` идемпотентен/безопасен без start, `_is_manifest_file` (абс/отн пути), удалён мёртвый `loader`; `hot_reload_enabled()` + 20 тестов (lifecycle, детекция, реальный reload манифеста через watchdog, env-флаг); smoke ON/OFF; Known Issue #8 → подключено (риски default-ON зафиксированы), новый Known Issue #14 (MockAdapter без start — BACKLOG Q7); полный прогон 29 failed (baseline) / 1374 passed (+20) | `src/main.py`, `src/services/config_watcher.py`, `tests/test_config_watcher.py` | ✅ Complete |
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

## Заметка о наблюдаемости

Полезно помнить про наблюдаемость: логи `adapters.ha_adapter` не имеют собственного
обработчика и наследуют корневой, где `info` не виден. Предупреждение (`warning`)
видно, `info` — нет. Проверка, добавленная на `info`, молчит и не доказывает ничего.
Это стоило пяти итераций в #70; теперь уровень записей проверяется кодом.

## Следующие шаги

Смотрите `03_ROADMAP.md` для детального плана развития.
