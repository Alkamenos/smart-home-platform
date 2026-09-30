---

description: "Task list template for feature implementation"
---

# Tasks: История операций с устройствами (ТР-010)

**Input**: Design documents from `/specs/005-device-audit-log/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/device-events-api.md](./contracts/device-events-api.md), [quickstart.md](./quickstart.md)

**Tests**: Включены — Constitution v3.0.0 (TDD NON-NEGOTIABLE), план R6 (Red-Green-Refactor).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)

## Path Conventions

Single project: `src/`, `tests/` at repository root (structure decision в plan.md).

---

## Phase 1: Setup

**Purpose**: Фиксация baseline перед изменением поведения

- [X] T001 Зафиксировать baseline фичи: прогнать `pytest tests/contract/test_device_events_api.py tests/integration/test_device_audit_log.py` (файлов ещё нет — зафиксировать отсутствие) и `pytest tests/contract -q` (текущее состояние: заглушка `GET /events` возвращает `[]`), записать результат в заметки к задачам

> **Baseline (2026-09-29)**: новые файлы тестов отсутствуют (T002-T003/T007/T008/T012/T015 — Red ожидаем); contract: **10 failed / 32 passed** (остатки pre-existing: devices/sources после header-фикса + websocket HA-адаптера); integration: **4 failed / 8 passed / 9 skipped**; unit: **10 failed / 216 passed**. Заглушка `GET /events` возвращает всегда `[]` (TODO в `devices.py:475`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Модель, персистентность и helper — ядро, без которого ни одна US не работает

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation** (TDD Red)

- [X] T002 [P] Unit-тесты модели `DeviceSyncEvent` в `tests/unit/test_device_sync_event.py`: сериализация `model_dump(mode="json")`, defaults (id/timestamp/user_id), валидация `action` (невалидное значение → ошибка Pydantic), None до/после по умолчанию (data-model.md) — Red: ImportError
- [X] T003 [P] Unit-тесты персистентности в `tests/unit/test_device_sync_persistence.py`: `append_event` + `list_events`, сортировка новые-первые, фильтр по action, пагинация limit/offset, отсутствие файла → `[]`, повреждённый JSON → `[]` + warning (research R6) — Red: ImportError
- [X] T004 Создать модель `DeviceSyncEvent` в `src/core/models/device_sync_event.py` (Pydantic BaseModel, поля по data-model.md: id/device_id/action Literal 5 значений/user_id default "system"/timestamp/before/after/data) + экспорт в `src/core/models/__init__.py` (depends: T002)
- [X] T005 Создать `DeviceSyncEventPersistence` в `src/core/persistence/devices.py` (append-only, `data/device_sync_events.json`, `append_event`/`list_events` с фильтром и пагинацией) + регистрация `self.device_sync_events` в `src/core/persistence/manager.py` (depends: T003, T004)
- [X] T006 Создать helper `get_sync_history(request) -> DeviceSyncEventPersistence | None` в `src/webui/routes/devices/deps.py` (читает `request.app.state.persistence`, guard None — паттерн `get_device_service`, research R3) (depends: T005)

**Checkpoint**: Модель и хранилище зелёные (unit), helper доступен — US могут начинаться

---

## Phase 3: User Story 1 - Просмотр истории операций устройства (Priority: P1) 🎯 MVP

**Goal**: `GET /api/v1/devices/{id}/events` отдаёт реальную историю; запись операции конфигурации с before/after и user_id; перезапуск сохраняет записи

**Independent Test**: Добавить запись через persistence напрямую → прочитать endpoint (чтение работает без US2/US3); затем `PUT config` → запись появляется; пересоздать persistence на том же `data_dir` → записи читаются

### Tests for User Story 1 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T007 [P] [US1] Contract-тесты в `tests/contract/test_device_events_api.py` по контракту (contracts/device-events-api.md): 200 + записи (запись добавлена напрямую через persistence в тесте), фильтр `event_type`, пагинация limit/offset, `event_type=nonexistent` → `[]`, 401/403/404, пустой список для устройства без операций (контрактные кейсы 1, 3, 5–9) — Red: заглушка возвращает всегда `[]`
- [X] T008 [P] [US1] Integration-тест в `tests/integration/test_device_audit_log.py`: `PUT /config` (admin) → история содержит `config_changed` с user_id и before/after (SC-001); «рестарт» — пересоздание app/PersistenceManager на том же tmp-`data_dir` → записи читаются (SC-003/FR-002) — Red: запись ещё не реализована

### Implementation for User Story 1

- [X] T009 [US1] Заменить заглушку чтением истории в `get_device_events` (`src/webui/routes/devices/devices.py`): `get_sync_history` → `list_events(device_id, event_type, limit, offset)` → маппинг `DeviceSyncEvent` → `DeviceEventResponse` (data: user_id/before/after/прочее, research R5); persistence None → `[]` (depends: T006, T007)
- [X] T010 [US1] Запись `config_changed` в `update_device_config` (`src/webui/routes/devices/devices.py`): копия config-полей ДО изменений (before), ПОСЛЕ (after), user_id из идентификации запроса; запись синхронно до ответа в try/except → loguru error, операция не фейлится (FR-009, clarify Q2) (depends: T006, T008)
- [X] T011 [US1] Прогнать T007+T008 до зелёного, `ruff check src/ tests/` — Checkpoint US1

**Checkpoint**: US1 полностью функциональна — просмотр истории и запись конфигурации работают независимо (MVP)

---

## Phase 4: User Story 2 - Автоматическая запись операций прав доступа (Priority: P2)

**Goal**: Каждые выдача/обновление/отзыв права попадают в историю с инициатором и ролью до→после

**Independent Test**: `POST access` + `DELETE access` → `GET .../events?event_type=access_granted` и `access_revoked` содержат записи; US1 при этом не менялась

### Tests for User Story 2 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T012 [P] [US2] Integration-тест в `tests/integration/test_device_audit_log.py`: grant (admin) → запись `access_granted` с `after.role` и инициатором (SC-002/FR-004); revoke → запись `access_revoked` с `before.role`; повторный grant с другой ролью → `access_updated` (depends: T007-чтение)

### Implementation for User Story 2

- [X] T013 [US2] Записи access-операций в grant/revoke хендлерах (`src/webui/routes/devices/access_control.py`): `access_granted`/`access_updated` (различие по наличию прежней роли)/`access_revoked` по таблице data-model.md; роль в before/after, получатель и инициатор в data/user_id; try/except → loguru error (FR-009) (depends: T006, T012)
- [X] T014 [US2] Прогнать T012 до зелёного — Checkpoint US2

---

## Phase 5: User Story 3 - Автоматическая запись команд (Priority: P3)

**Goal**: Каждая отправленная команда фиксируется с инициатором и содержимым; before/after пустые (clarify Q1)

**Independent Test**: `POST /command` (controller) → `GET .../events?event_type=command_executed` содержит запись с данными команды

### Tests for User Story 3 ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [X] T015 [P] [US3] Contract-тест в `tests/contract/test_device_events_api.py` или integration в `tests/integration/test_device_audit_log.py`: `POST /command` → запись `command_executed` с user_id и содержимым команды в data, `before`/`after` пустые (SC-001/FR-005/clarify Q1) (depends: чтение из US1)

### Implementation for User Story 3

- [X] T016 [US3] Запись `command_executed` в `execute_device_command` (`src/webui/routes/devices/devices.py`): data = `{command: <effective_name>, parameters: ...}` (что доступно из CommandRequest), before/after = None, user_id из идентификации; try/except → loguru error (depends: T006, T015)
- [X] T017 [US3] Прогнать T015 до зелёного — Checkpoint US3

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Валидация, регресс, документация

- [X] T018 Прогнать quickstart-сценарии 1–6 (`specs/005-device-audit-log/quickstart.md`) и внести статусы в карту сценариев — 6/6 ✅
- [X] T019 Полный регресс: `pytest tests/contract`, `pytest tests/integration`, `pytest tests/` (сравнить с baseline T001 — новых падений нет), `.ai/scripts/run_checks.sh` exit 0
  - contract: 10 failed / 40 passed — падения идентичны baseline T001 (url-normalize, выдуманные UUID, HAWebSocketClient), +8 новых зелёных
  - integration: 4 failed / 13 passed / 9 skipped — падения идентичны baseline, +5 новых зелёных
  - `run_checks.sh` exit 0, coverage 93.0% (min 80)
  - root (`tests/`): 87 failed / 1243 passed = baseline 78 + 9 (`tests/unit/test_device_sync_persistence.py`)
  - Причина 9: **pre-existing заражение** `tests/test_webui_playwright.py` — его async-тесты оставляют живой event loop в главном потоке (`Runner.run() cannot be called from a running event loop`); в root-порядке ломает ВСЕ последующие async-тесты (в baseline этому подвержены 51 device_service и др.)
  - Доказательства: root **без** playwright → 15 failed / 1301 passed; `tests/unit` отдельно → мои 9 зелёные (failed только baseline 10); даже синхронный probe с `asyncio.run()` падает после playwright-файла
  - Вывод: новых падений от фичи нет; заражение вынесено в Known Issue (см. `.ai/01_PROJECT_STATE.md`)
- [X] T020 [P] Документация: `.ai/01_PROJECT_STATE.md` — changelog + закрыть связанные пункты (CHK013/бэклог ТР-010), `.ai/03_ROADMAP.md` — Tech Debt #2 закрыт, `specs/001-device-integration/tasks.md` — RU T041 отметить `[x]`, `specs/001/checklists/requirements.md` — CHK013, `python3 .ai/scripts/sync_roadmap.py --auto-update` — выполнено + добавлен Known Issue #13 (playwright loop-заражение, найдено при T019)
- [X] T021 Статусы фичи: `specs/005-device-audit-log/spec.md` → Implemented (2026-09-30), `checklists/requirements.md` — 16/16, quickstart-карта — 6/6 ✅
- [ ] T022 Коммит: `run_checks.sh` exit 0 → `feat(...)` по формату конституции (после ревью пользователем)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — MVP
- **US2 (Phase 4)**: Depends on Foundational + чтение US1 (T009)
- **US3 (Phase 5)**: Depends on Foundational + чтение US1 (T009)
- **Polish (Phase 6)**: Depends on desired stories (US1 минимум; US2+US3 — полный scope)

### User Story Dependencies

- **US1 (P1)**: после Foundational, без зависимостей от US2/US3
- **US2 (P2)**: после Foundational; использует чтение из US1 (T009)
- **US3 (P3)**: после Foundational; использует чтение из US1 (T009)

### Within Each User Story

- Tests FIRST (Red) → implementation (Green) → прогон чекпоинта

### Parallel Opportunities

- T002 ∥ T003 (разные unit-файлы)
- T007 ∥ T008 (contract ∥ integration)
- T012 ∥ T015 (US2 ∥ US3 тесты, разные сценарии)
- T020 — параллельно с остальным Polish

---

## Parallel Example: User Story 1

```bash
# Тесты US1 вместе (Red):
Task: "T007 Contract-тесты GET /events в tests/contract/test_device_events_api.py"
Task: "T008 Integration-тест config+рестарт в tests/integration/test_device_audit_log.py"

# Затем implementation (Green):
Task: "T009 чтение в get_device_events"
Task: "T010 запись config_changed в update_device_config"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + Phase 2 (Foundation)
2. Phase 3 (US1) — история видна через API, config пишется
3. **STOP and VALIDATE**: прогон quickstart-сценариев 1, 4, 5, 6
4. Демо/коммит возможен

### Incremental Delivery

1. Foundation → US1 (просмотр + config) → MVP
2. US2 → права в истории → SC-002
3. US3 → команды в истории → SC-001 полный
4. Polish → регресс + доки + статусы

---

## Notes

- [P] tasks = different files, no dependencies
- Все доменные файлы (`device_service.py`, `event_bus`, `EventStore`) не изменяются (research R1/R2)
- Запись истории НИКОГДА не фейлит основную операцию (FR-009) — проверять в каждом хендлере
- Commit после каждой логической группы (Constitution: format `type(scope): description`)
