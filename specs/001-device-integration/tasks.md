# Задачи реализации: Интеграция и конфигурирование устройств

**Статус**: Сгенерирован `/speckit-tasks` | **Дата**: 2026-09-29

**Базис**: [spec.md](spec.md), [plan.md](plan.md), [data-model.md](data-model.md), [contracts/](contracts/), [research.md](research.md)

**Язык кодирования**: Python 3.10+ | **Тестирование**: TDD (тесты перед реализацией)

---

## Обзор фаз реализации

| Фаза | Название | Назначение | Статус |
|------|----------|-----------|--------|
| **Phase 1** | Setup | Инициализация проекта и инфраструктура | 📋 |
| **Phase 2** | Foundational | Blocking prerequisites (модели, персистентность) | 📋 |
| **Phase 3** | US1 (P1) | Синхронизация устройств из HA | 📋 |
| **Phase 4** | US2 (P1) | Конфигурирование параметров устройства | 📋 |
| **Phase 5** | US3 (P2) | Управление состоянием устройств | 📋 |
| **Phase 6** | US4 (P2) | Управление доступом к устройствам | 📋 |
| **Phase 7** | Polish | Cross-cutting concerns и финализация | 📋 |

**MVP Scope**: Phase 1 + Phase 2 + Phase 3 + Phase 4

---

## Формат задач

```
- [ ] [ID] [P?] [Story?] Описание с путем файла
```

- **Checkbox**: Всегда `- [ ]` (markdown)
- **[ID]**: Последовательный номер (T001, T002, ...)
- **[P]**: Только если задача может выполняться параллельно (разные файлы, нет зависимостей)
- **[Story]**: ТОЛЬКО для фаз с US (US1, US2, US3, US4) — не нужно для Setup/Foundational/Polish
- **Описание**: Точное действие с путем файла

**Примеры**:
- ✅ `- [ ] T001 Создать структуру проекта`
- ✅ `- [ ] T005 [P] Создать модель HASource в src/core/models/ha_source.py`
- ✅ `- [ ] T021 [P] [US1] Написать contract тест в tests/contract/test_sources_api.py`
- ✅ `- [ ] T024 [US1] Реализовать sync_devices_from_source() в src/services/device_service.py`
- ❌ `- [ ] T001 [P] Setup` (нет деталей)

---

## Phase 1: Setup (Инициализация проекта)

**Назначение**: Проектная структура и базовая инфраструктура

**Контрольная точка**: Setup завершен — готово к реализации основных компонентов

### Setup Tasks

- [ ] T001 Создать пакет `src/adapters/home_assistant/` с `__init__.py`
- [ ] T002 Создать пакет `src/services/` с базовыми файлами (`__init__.py`, `__all__`)
- [ ] T003 [P] Создать пакет `src/core/models/` с `__init__.py` для моделей Device
- [ ] T004 [P] Создать пакет `src/core/persistence/` с `__init__.py` для хранилища
- [ ] T005 [P] Создать пакет `tests/unit/adapters/` для тестов адаптера
- [ ] T006 [P] Создать пакет `tests/integration/` для интеграционных тестов
- [ ] T007 [P] Создать пакет `tests/contract/` для тестов контрактов
- [ ] T008 Обновить `pyproject.toml`: добавить зависимости (aiohttp, websockets, если не добавлены)
- [ ] T009 Создать `.env.example` с примерами переменных (HA_URL, HA_TOKEN, ENCRYPTION_KEY)

---

## Phase 2: Foundational (Базовые компоненты - BLOCKING)

**Назначение**: Модели, безопасность, персистентность — БЛОКИРУЮЩИЕ для всех user stories

**Предусловие**: Phase 1 завершена

**⚠️ КРИТИЧЕСКОЕ**: Эта фаза ДОЛЖНА быть завершена перед началом работы над US1-US4

### 2.1 Security (Шифрование)

- [ ] T010 Создать `src/core/security/encryption.py` с функциями шифрования (encrypt/decrypt использовать cryptography.fernet)
- [ ] T011 Написать unit тесты в `tests/unit/core/test_encryption.py` (TDD: тесты ПАДАЮТ перед реализацией)

### 2.2 Pydantic Models

- [ ] T012 [P] Создать модель HASource в `src/core/models/ha_source.py` (полями: id, name, url, token шифруется, status, last_sync, last_error, created_at, updated_at)
- [ ] T013 [P] Создать модель Device в `src/core/models/device.py` (полями: id, ha_entity_id, ha_source_id, device_name, device_type, model, manufacturer, state, status, last_state_update, created_at, updated_at)
- [ ] T014 [P] Создать модель DeviceConfig в `src/core/models/device_config.py` (полями: id, device_id, display_name уникальна в source, description, location, tags, notes, enabled, custom_settings, created_by, updated_by, created_at, updated_at)
- [ ] T015 [P] Создать модель DeviceCommand в `src/core/models/device_command.py` (полями: id, device_id, name, ha_service, description, parameters, return_type, execution_timeout, is_safe, created_at)
- [ ] T016 [P] Создать модель DeviceSyncEvent в `src/core/models/device_sync_event.py` (полями: id, device_id, event_type, details, user_id, timestamp, trace_id)
- [ ] T017 [P] Создать модель DeviceAccess в `src/core/models/device_access.py` (полями: id, device_id, user_id, role, created_at)
- [ ] T018 Создать `src/core/models/__init__.py` с экспортом всех моделей

### 2.3 Persistence Layer

- [ ] T019 [P] Создать `src/core/persistence/ha_sources.py` с функциями CRUD для HASource (create, get, list, update, delete)
- [ ] T020 [P] Создать `src/core/persistence/devices.py` с функциями CRUD для Device (create, get, list, update, delete, find_by_entity_id)
- [ ] T021 [P] Создать `src/core/persistence/device_configs.py` с функциями CRUD для DeviceConfig
- [ ] T022 [P] Создать `src/core/persistence/device_commands.py` с функциями CRUD для DeviceCommand
- [ ] T023 [P] Создать `src/core/persistence/device_sync_events.py` для логирования DeviceSyncEvent
- [ ] T024 [P] Создать `src/core/persistence/device_access.py` для DeviceAccess (Phase 6)
- [ ] T025 Создать `src/core/persistence/__init__.py` с экспортом функций хранилища

### 2.4 Unit Tests for Models & Persistence

- [ ] T026 [P] Написать unit тесты для всех моделей в `tests/unit/core/models/test_*.py` (TDD: ПАДАЮТ перед реализацией, покрытие >= 100%)
- [ ] T027 [P] Написать unit тесты для persistence в `tests/unit/core/persistence/test_*.py` (TDD: ПАДАЮТ перед реализацией, покрытие >= 95%)

**Checkpoint**: Фундамент готов — модели, безопасность и персистентность работают

---

## Phase 3: User Story 1 (P1) - Синхронизация устройств из Home Assistant

**Цель**: Администратор может подключить HA, загрузить полный список устройств и видеть их в системе

**Независимое тестирование**: (1) добавить источник HA, (2) запустить синхронизацию, (3) видеть устройства в /api/devices, (4) после перезагрузки устройства остаются

**Предусловие**: Phase 2 завершена

### 3.1 Contract Tests (TDD - тесты сначала!)

- [ ] T028 [P] [US1] Написать contract тесты в `tests/contract/test_device_sources_api.py` (POST create, GET retrieve, POST sync, validation)
- [ ] T029 [P] [US1] Написать contract тесты в `tests/contract/test_device_sync_api.py` (GET /api/devices, GET /api/devices/{id})

### 3.2 Home Assistant Adapter

- [ ] T030 [US1] Создать `src/adapters/home_assistant/rest_client.py` с HARestClient (get_states, get_config, error handling)
- [ ] T031 [P] [US1] Создать `src/adapters/home_assistant/websocket_client.py` с HAWebSocketClient (connect, subscribe, get_events, disconnect)
- [ ] T032 [P] [US1] Создать `src/adapters/home_assistant/connection_manager.py` для управления подключением и reconnection logic
- [ ] T033 [P] [US1] Создать `src/adapters/home_assistant/models.py` с Pydantic моделями для HA entities (HAState, HADevice)
- [ ] T034 [US1] Создать `src/adapters/home_assistant/__init__.py` с экспортом клиентов

### 3.3 Device Service

- [ ] T035 [US1] Создать `src/services/device_service.py` с методом load_devices_from_ha(source) и sync_source(source_id)
- [ ] T036 [P] [US1] Создать события в `src/core/events/device_events.py` (DeviceLoadedEvent, DeviceSyncStartedEvent, DeviceSyncCompletedEvent)

### 3.4 WebUI Routes

- [ ] T037 [US1] Создать `src/webui/routes/devices/sources.py` с endpoints: POST /api/devices/sources, GET /api/devices/sources, GET /api/devices/sources/{id}, PUT, DELETE, POST /api/devices/sources/{id}/sync
- [ ] T038 [P] [US1] Создать `src/webui/routes/devices/devices.py` с endpoints: GET /api/devices, GET /api/devices/{id}

### 3.5 Integration Tests

- [ ] T039 [P] [US1] Написать integration тесты в `tests/integration/test_device_sync.py` (load_devices_from_ha, sync_source, event publishing)
- [ ] T040 [P] [US1] Написать E2E тесты в `tests/integration/test_device_sync_e2e.py` (полные сценарии загрузки)

**Checkpoint**: US1 complete — администратор может загружать устройства из HA

---

## Phase 4: User Story 2 (P1) - Конфигурирование параметров устройства

**Цель**: Администратор может редактировать параметры устройства (название, описание, теги, местоположение)

**Независимое тестирование**: (1) получить конфигурацию, (2) обновить параметры, (3) проверить сохранение, (4) после перезагрузки параметры остались

**Предусловие**: Phase 2 + Phase 3 завершены

### 4.1 Contract Tests

- [ ] T041 [P] [US2] Написать contract тесты в `tests/contract/test_device_config_api.py` (GET config, PUT update, validation, uniqueness)

### 4.2 DeviceConfig Service

- [ ] T042 [US2] Расширить `src/services/device_service.py` методом update_device_config(device_id, user_id, config_update)

### 4.3 WebUI Routes

- [ ] T043 [US2] Расширить `src/webui/routes/devices/devices.py` endpoints для config: GET /api/devices/{id}, PUT /api/devices/{id}/config

### 4.4 Events

- [ ] T044 [US2] Расширить `src/core/events/device_events.py` событием DeviceConfigChangedEvent

### 4.5 Integration & E2E Tests

- [ ] T045 [P] [US2] Написать integration тесты в `tests/integration/test_device_config.py` (update, uniqueness, persistence)
- [ ] T046 [P] [US2] Написать E2E тесты в `tests/integration/test_device_config_e2e.py` (полные сценарии конфигурирования)

**Checkpoint**: US2 complete — конфигурирование работает для всех параметров

---

## Phase 5: User Story 3 (P2) - Управление состоянием устройств

**Цель**: Пользователи видят текущее состояние устройств (синхронизировано <= 5 сек) и могут отправлять команды

**Независимое тестирование**: (1) состояние синхронизируется из HA, (2) пользователь отправляет команду, (3) команда выполняется в HA

**Предусловие**: Phase 2 + Phase 3 + Phase 4 завершены

### 5.1 WebSocket Sync Service

- [ ] T047 [US3] Создать `src/services/sync_service.py` с DeviceSyncService (start, subscribe_to_source, on_state_changed)
- [ ] T048 [P] [US3] Расширить DeviceService методом send_command(device_id, user_id, command, params)

### 5.2 Contract Tests

- [ ] T049 [P] [US3] Написать contract тесты в `tests/contract/test_device_state_api.py` (GET state, POST command, GET events)

### 5.3 WebUI Routes

- [ ] T050 [US3] Расширить `src/webui/routes/devices/devices.py` endpoints для команд: POST /api/devices/{id}/command
- [ ] T051 [P] [US3] Создать `src/webui/routes/devices/events.py` с GET /api/devices/{id}/events

### 5.4 Events

- [ ] T052 [US3] Расширить `src/core/events/device_events.py` событиями DeviceStateChangedEvent, DeviceCommandSentEvent, DeviceCommandFailedEvent

### 5.5 Integration Tests

- [ ] T053 [P] [US3] Написать integration тесты в `tests/integration/test_device_state_sync.py` (sync, command execution, error handling)
- [ ] T054 [P] [US3] Написать E2E тесты в `tests/integration/test_device_commands_e2e.py` (полные сценарии команд)

**Checkpoint**: US3 complete — состояние синхронизируется и команды работают

---

## Phase 6: User Story 4 (P2) - Управление доступом к устройствам

**Цель**: Администратор может назначать доступ к устройствам (viewer, controller, admin)

**Независимое тестирование**: (1) назначить доступ, (2) пользователь видит устройство, (3) viewer не может выполнять команды, (4) controller может

**Предусловие**: Phase 2 + Phase 3 + Phase 4 + Phase 5 завершены

### 6.1 DeviceAccess Service

- [ ] T055 [US4] Расширить `src/services/device_service.py` методами grant_access, revoke_access, get_user_devices, check_access

### 6.2 Middleware

- [ ] T056 [US4] Создать `src/webui/middleware_device_access.py` для проверки доступа к Device endpoints

### 6.3 Contract Tests

- [ ] T057 [P] [US4] Написать contract тесты в `tests/contract/test_device_access_api.py` (grant, revoke, role validation)

### 6.4 WebUI Routes

- [ ] T058 [US4] Создать `src/webui/routes/devices/access.py` с POST grant, DELETE revoke, GET list (admin only)

### 6.5 Integration Tests

- [ ] T059 [P] [US4] Написать integration тесты в `tests/integration/test_device_access.py` (grant, revoke, get_user_devices)
- [ ] T060 [P] [US4] Написать E2E тесты в `tests/integration/test_device_access_e2e.py` (полные сценарии доступа)

**Checkpoint**: US4 complete — доступ контролируется

---

## Phase 7: Polish & Cross-Cutting Concerns

**Назначение**: Улучшения, которые затрагивают несколько US

**Предусловие**: All US completed (Phase 3-6)

### 7.1 Documentation

- [ ] T061 Обновить README.md с разделом Device Integration (quick start, API docs)
- [ ] T062 Создать `docs/device-integration-guide.md` с руководством администратора
- [ ] T063 [P] Обновить docstrings всех публичных функций (Google style)

### 7.2 Testing & Coverage

- [ ] T064 Запустить pytest с --cov (проверить >= 85% для adapters, >= 90% для services, >= 100% для models)
- [ ] T065 [P] Добавить недостающие unit тесты для edge cases
- [ ] T066 [P] Запустить все integration тесты (должны пройти)
- [ ] T067 [P] Запустить все E2E тесты (должны пройти, validate quickstart.md scenarios)

### 7.3 Code Quality

- [ ] T068 Запустить ruff lint и fix (ruff check --fix src/ tests/)
- [ ] T069 Запустить ruff format (ruff format src/ tests/)
- [ ] T070 Запустить mypy для type checking (mypy src/ --strict)
- [ ] T071 [P] Запустить pre-commit хуки (.ai/scripts/setup_hooks.sh)

### 7.4 Performance & Security

- [ ] T072 Написать load test для Device sync (100-500 устройств < 1 min)
- [ ] T073 [P] Профайлировать key functions (load_devices_from_ha, send_command, update_device_config)
- [ ] T074 Security audit (tokens не логируются, все API endpoints валидируют permissions, input санитизирован)
- [ ] T075 [P] Проверить ENCRYPTION_KEY (32+ chars, только env, .env.example содержит placeholder)

### 7.5 Finalization

- [ ] T076 Обновить `specs/001-device-integration/tasks.md` (пометить все [x])
- [ ] T077 Запустить `.ai/scripts/run_checks.sh` (все проверки должны пройти)
- [ ] T078 Создать финальный commit с feat(device-integration): complete implementation message
- [ ] T079 [P] Запустить все quickstart.md сценарии (Scenario 1-4 все ✅)

**Checkpoint**: Вся фича завершена, протестирована, и готова к продакшену

---

## Зависимости и порядок выполнения

### Обязательный порядок

```
Phase 1 (Setup)
    ↓
Phase 2 (Foundational) ← БЛОКИРУЕТ всё остальное
    ↓
Phase 3 (US1: Sync) ← MVP часть 1
    ↓
Phase 4 (US2: Config) ← MVP часть 2
    ├→ Phase 5 (US3: State) (параллельно если ресурсы)
    │   └→ Phase 6 (US4: Access)
    └→ (параллельно Phase 5)
        └→ Phase 7 (Polish)
```

### Параллельные возможности

- **Phase 1**: Все Setup задачи [P] параллельно
- **Phase 2**: Все [P] задачи параллельно (Models, Persistence независимы)
- **Phase 3-4**: Могут быть параллельны (разные файлы)
- **Phase 5-6**: Могут быть параллельны (разные endpoints и services)

---

## MVP Scope & Delivery

**MVP** = Phase 1 + Phase 2 + Phase 3 + Phase 4 (готово к демонстрации)

**Post-MVP** = Phase 5 + Phase 6 (дополнительные функции)

---

**Версия**: 1.0.0 | **Дата генерации**: 2026-09-29 | **Статус**: Ready for Implementation

---

## Фаза 4: История пользователя 2 - Конфигурирование параметров устройства (Приоритет: P1)

**Цель**: Администратор может редактировать параметры каждого загруженного устройства (название, описание, расположение, теги)

**Независимое тестирование**: Задача полностью протестирована если администратор может: (1) загрузить устройство через History 1, (2) получить текущую конфигурацию через API, (3) отредактировать параметры конфигурации, (4) проверить что изменения сохранились и восстановились после перезагрузки

### Тесты для истории пользователя 2 (тесты ОБЯЗАТЕЛЬНЫ)

> **ПРИМЕЧАНИЕ: Написать эти тесты СНАЧАЛА, убедиться что они ПАДАЮТ перед реализацией**

- [ ] T032 [P] [US2] Контрактный тест для PUT /api/v1/devices/{id}/config в `tests/contract/test_devices_api.py` - проверить обновление конфигурации с валидацией полей
- [ ] T033 [P] [US2] Контрактный тест для GET /api/v1/devices/{id} в `tests/contract/test_devices_api.py` - проверить получение полной информации об устройстве с конфигурацией
- [ ] T034 [US2] Интеграционный тест для полного потока редактирования конфигурации в `tests/integration/test_device_config.py` - загрузка, редактирование, проверка сохранения (зависит от T032-T033)

### Реализация истории пользователя 2

- [ ] T035 [US2] Расширить модель `DeviceConfig` валидацией: display_name (min 1, max 255, уникальна), description (max 1000), location (max 255), tags (макс 10 тегов по 50 символов) в `src/core/models/device_config.py`
- [ ] T036 [US2] Реализовать метод `update_device_config()` в `DeviceService` для обновления конфигурации (зависит от T035)
- [ ] T037 [US2] Реализовать методы сохранения/загрузки DeviceConfig в слое персистентности в `src/core/persistence/devices.py`
- [ ] T038 [US2] Создать FastAPI route `PUT /api/v1/devices/{id}/config` в `src/webui/routes/devices/devices.py` для обновления конфигурации (зависит от T036)
- [ ] T039 [US2] Расширить FastAPI route `GET /api/v1/devices/{id}` для возврата полной информации об устройстве с конфигурацией, командами и событиями
- [ ] T040 [US2] Публиковать `DeviceConfigChangedEvent` при каждом изменении конфигурации через EventBus
- [ ] T041 [US2] Создать SyncEvent запись для каждого изменения конфигурации с информацией о пользователе (ТР-010)
- [ ] T042 [US2] Реализовать сохранение конфигурации при перезагрузке (ТР-003 и КУ-003)

**Контрольная точка**: Истории пользователя 1 И 2 должны работать независимо. Конфигурация сохраняется в БД и восстанавливается при перезагрузке (КУ-003).

---

## Фаза 5: История пользователя 3 - Управление состоянием устройств (Приоритет: P2)

**Цель**: Администратор и пользователи могут видеть текущее состояние устройств и отправлять команды в Home Assistant

**Независимое тестирование**: Задача полностью протестирована если: (1) состояние устройств синхронизируется в реальном времени <= 5 сек (КУ-004), (2) пользователь может отправить команду и она выполнится в HA (КУ-005), (3) ошибки обрабатываются корректно

### Тесты для истории пользователя 3 (тесты ОБЯЗАТЕЛЬНЫ)

> **ПРИМЕЧАНИЕ: Написать эти тесты СНАЧАЛА, убедиться что они ПАДАЮТ перед реализацией**

- [ ] T043 [P] [US3] Контрактный тест для WebSocket подписки в `tests/contract/test_websocket.py` - проверить subscribe и получение событий state_changed
- [ ] T044 [P] [US3] Контрактный тест для POST /api/v1/devices/{id}/command в `tests/contract/test_devices_api.py` - проверить отправку команд
- [ ] T045 [P] [US3] Контрактный тест для GET /api/v1/devices/{id}/events в `tests/contract/test_devices_api.py` - проверить историю операций
- [ ] T046 [US3] Интеграционный тест для синхронизации состояния через WebSocket в `tests/integration/test_state_sync.py` - проверить задержку <= 5 сек (КУ-004)
- [ ] T047 [US3] Интеграционный тест для отправки команд в `tests/integration/test_commands.py` - отправка команды, проверка выполнения, обработка ошибок (зависит от T043-T046)

### Реализация истории пользователя 3

- [ ] T048 [P] [US3] Создать модель `DeviceCommand` в `src/core/models/device_command.py` с полями: id, device_id, name (уникальна в пределах устройства), ha_service (формат: domain.service), description, parameters (dict), return_type, execution_timeout (макс 300 сек), is_safe (зависит от T008)
- [ ] T049 [P] [US3] Реализовать метод `subscribe_to_state_changes()` в `HAWebSocketClient` для подписки на события HA через WebSocket
- [ ] T050 [US3] Реализовать метод `handle_state_change()` в `DeviceService` для обновления состояния Device и публикации события через EventBus (зависит от T049)
- [ ] T051 [US3] Создать обработчик WebSocket соединения в FastAPI в `src/webui/routes/devices/websocket.py` (зависит от T050)
- [ ] T052 [US3] Реализовать route `ws://api/v1/ws/devices` с подпиской на события для синхронизации состояния (зависит от T051)
- [ ] T053 [US3] Реализовать метод `execute_command()` в `DeviceService` для отправки команд в HA (зависит от T048, зависит от HARestClient)
- [ ] T054 [US3] Создать FastAPI route `POST /api/v1/devices/{id}/command` в `src/webui/routes/devices/devices.py` для отправки команд (зависит от T053)
- [ ] T055 [US3] Реализовать асинхронное отслеживание статуса команды с polling или callback (зависит от T054)
- [ ] T056 [US3] Создать FastAPI route `GET /api/v1/devices/{id}/command/{command_id}` для получения статуса команды (зависит от T055)
- [ ] T057 [US3] Создать FastAPI route `GET /api/v1/devices/{id}/events` в `src/webui/routes/devices/devices.py` для получения истории операций (зависит от T008)
- [ ] T058 [US3] Публиковать `DeviceStateChangedEvent` при каждом изменении состояния через EventBus
- [ ] T059 [US3] Добавить обработку ошибок при отправке команд и информирование пользователя (ТР-008, КУ-005)
- [ ] T060 [US3] Реализовать отслеживание недоступных устройств и изменение статуса на unavailable при отсутствии обновлений > 60 сек (зависит от T050)

**Контрольная точка**: История пользователя 3 работает независимо от 1-2. Состояние синхронизируется <= 5 сек (КУ-004), команды выполняются успешно (КУ-005).

---

## Фаза 6: История пользователя 4 - Управление доступом к устройствам (Приоритет: P2)

**Цель**: Администратор может контролировать доступ к устройствам на основе ролей пользователей

**Независимое тестирование**: Задача протестирована если: (1) администратор может назначить роль пользователю, (2) пользователь без прав не может видеть/управлять устройством, (3) права проверяются во всех endpoints

### Тесты для истории пользователя 4 (тесты ОБЯЗАТЕЛЬНЫ)

> **ПРИМЕЧАНИЕ: Написать эти тесты СНАЧАЛА, убедиться что они ПАДАЮТ перед реализацией**

- [ ] T061 [P] [US4] Контрактный тест для проверки прав доступа в `tests/contract/test_access_control.py` - проверить 403 без прав
- [ ] T062 [P] [US4] Контрактный тест для управления правами в `tests/contract/test_access_control.py` - проверить назначение ролей
- [ ] T063 [US4] Интеграционный тест для полного потока управления доступом в `tests/integration/test_access_control.py` - назначение прав, проверка доступа (зависит от T061-T062)

### Реализация истории пользователя 4

- [ ] T064 [US4] Создать модель `DeviceAccess` в `src/core/models/device_access.py` с полями: id, device_id, user_id, role (viewer, controller, admin), granted_by, created_at
- [ ] T065 [US4] Добавить методы сохранения/загрузки DeviceAccess в слой персистентности
- [ ] T066 [US4] Реализовать функцию проверки прав доступа `check_device_access()` в `DeviceService` (зависит от T064)
- [ ] T067 [US4] Добавить middleware проверки прав доступа для всех endpoints устройств в `src/webui/routes/devices/` (зависит от T066)
- [ ] T068 [US4] Создать FastAPI routes для управления доступом в `src/webui/routes/devices/access_control.py`: POST (назначить доступ), DELETE (отозвать), GET (список доступа) (зависит от T066)
- [ ] T069 [US4] Реализовать фильтрацию устройств по доступу в `GET /api/v1/devices` (пользователь видит только доступные устройства) (зависит от T066)
- [ ] T070 [US4] Создать SyncEvent запись для каждого изменения прав доступа (ТР-010)
- [ ] T071 [US4] Добавить проверку доступа для WebSocket подписок (зависит от T067)

**Контрольная точка**: Все истории пользователя (1-4) работают независимо. Система обеспечивает безопасность доступа.

---

## Фаза 7: Полировка и кросс-функциональные аспекты

**Назначение**: Улучшения, влияющие на несколько историй пользователя

- [ ] T072 [P] Обновить документацию API в docs/api/device-integration-api.md
- [ ] T073 [P] Добавить примеры использования в docs/api/device-integration-examples.md
- [ ] T074 [P] Создать миграцию/скрипт инициализации БД для таблиц источников и устройств в `src/core/persistence/migrations/`
- [ ] T075 [P] Добавить unit тесты для всех сервис методов в `tests/unit/test_device_service.py`
- [ ] T076 [P] Добавить unit тесты для всех моделей валидации в `tests/unit/test_models.py`
- [ ] T077 Оптимизация производительности: кэширование списка устройств, индексирование БД по source_id и device_type
- [ ] T078 [P] Оптимизация: батчинг синхронизации состояния при получении событий через WebSocket
- [ ] T079 Добавить метрики Prometheus для отслеживания: время синхронизации, количество команд, ошибки соединения
- [ ] T080 Запустить полную валидацию quickstart.md (все 6 сценариев)
- [ ] T081 Окончательная проверка логирования: убедиться что все операции логируются с пользователем и временем (ТР-010)
- [ ] T082 Проверка безопасности: убедиться что токены не логируются и не попадают в ошибки (ТР-008)

---

## Зависимости и порядок выполнения

### Зависимости между фазами

- **Настройка (Фаза 1)**: Нет зависимостей - может начаться немедленно
- **Фундаментальная (Фаза 2)**: Зависит от завершения Настройки - **БЛОКИРУЕТ все истории пользователя**
- **Истории пользователя (Фазы 3-6)**: Все зависят от завершения Фундаментальной фазы
  - История 1 (US1): Может начаться после Фундаментальной - нет зависимостей от других историй
  - История 2 (US2): Может начаться после Фундаментальной - может зависеть от US1, но должна быть независимо тестируемой
  - История 3 (US3): Может начаться после Фундаментальной - может зависеть от US1-US2
  - История 4 (US4): Может начаться после Фундаментальной - может зависеть от US1-US3
- **Полировка (Фаза 7)**: Зависит от завершения всех нужных историй пользователя

### Зависимости внутри каждой истории пользователя

- Тесты ДОЛЖНЫ быть написаны и ДОЛЖНЫ ПАДАТЬ до реализации
- Модели перед сервисами
- Сервисы перед endpoints
- Ядро реализации перед интеграцией
- История завершена перед переходом к следующей приоритету

### Возможности параллелизма

- Все задачи Настройки помечены [P] могут выполняться параллельно
- Все задачи Фундаментальной фазы помечены [P] могут выполняться параллельно (в пределах Фазы 2)
- **КРИТИЧНО**: Фундаментальная фаза ДОЛЖНА завершиться перед началом любых историй пользователя
- После завершения Фундаментальной, все истории пользователя могут начаться параллельно (если есть ресурсы)
- Все тесты для истории помечены [P] могут выполняться параллельно
- Модели в истории помечены [P] могут выполняться параллельно
- Разные истории пользователя могут разрабатываться параллельно разными командами

### Пример параллелизма: История пользователя 1

```bash
# Запустить все тесты для US1 одновременно:
T016: Контрактный тест POST /api/v1/devices/sources
T017: Контрактный тест GET /api/v1/devices/sources/{id}
T018: Контрактный тест POST /api/v1/devices/sources/{id}/sync
T019: Контрактный тест GET /api/v1/devices

# Запустить все методы клиента одновременно:
T021: connect_to_ha()
T022: fetch_devices()
```

---

## Стратегия реализации

### MVP первый (только История пользователя 1)

1. Завершить Фазу 1: Настройка
2. Завершить Фазу 2: Фундаментальная (КРИТИЧНО - блокирует всех)
3. Завершить Фазу 3: История пользователя 1
4. **ОСТАНОВИТЬ и ВАЛИДИРОВАТЬ**: Протестировать US1 независимо (требование КУ-001 и КУ-002)
5. Развернуть/демонстрация если готово

### Инкрементальная доставка

1. Завершить Настройку + Фундаментальную → Foundation готова
2. Добавить US1 → Протестировать независимо → Развернуть/Demo (MVP!)
3. Добавить US2 → Протестировать независимо → Развернуть/Demo
4. Добавить US3 → Протестировать независимо → Развернуть/Demo
5. Добавить US4 → Протестировать независимо → Развернуть/Demo
6. Каждая история добавляет ценность без нарушения предыдущих историй

### Стратегия параллельной команды

С несколькими разработчиками:

1. Команда завершает Настройку + Фундаментальную вместе
2. После завершения Фундаментальной:
   - Разработчик А: История пользователя 1 (US1)
   - Разработчик Б: История пользователя 2 (US2)
   - Разработчик В: История пользователя 3 (US3)
3. Истории завершаются и интегрируются независимо

---

## Заметки

- [P] задачи = разные файлы, нет зависимостей
- [Story] метка связывает задачу с конкретной историей пользователя для отслеживания
- Каждая история пользователя должна быть независимо завершаемой и тестируемой
- Убедиться что тесты падают перед реализацией
- Коммитить после каждой задачи или логической группы
- Остановить на любой контрольной точке для валидации истории независимо
- Избегать: неясные задачи, конфликты одного файла, кросс-история зависимости, которые нарушают независимость

---

## Статистика задач

| Фаза | Задачи | Описание |
|------|--------|---------|
| Фаза 1: Настройка | T001-T004 | 4 задачи инфраструктуры |
| Фаза 2: Фундаментальная | T005-T015 | 11 задач ядра |
| Фаза 3: US1 (P1) MVP | T016-T031 | 16 задач (5 тестов + 11 реализации) |
| Фаза 4: US2 (P1) | T032-T042 | 11 задач (3 теста + 8 реализации) |
| Фаза 5: US3 (P2) | T043-T060 | 18 задач (5 тестов + 13 реализации) |
| Фаза 6: US4 (P2) | T061-T071 | 11 задач (3 теста + 8 реализации) |
| Фаза 7: Полировка | T072-T082 | 11 задач кросс-функциональные |
| **ИТОГО** | **T001-T082** | **82 задачи** |

---

**Версия**: 1.0 | **Статус**: Список задач завершен | **Дата**: 2026-09-29
