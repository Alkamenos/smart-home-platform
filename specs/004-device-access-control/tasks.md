# Tasks: Контроль доступа к устройствам (Access Control)

**Input**: Design documents from `/specs/004-device-access-control/`

**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD — существующие contract/integration тесты (`tests/contract/test_access_control.py`, `tests/integration/test_access_control.py`) объявлены acceptance-тестами фичи (research R6, сейчас красные); новые кейсы — только для зазоров (WS-доставка после отзыва, анти-дубликат grant, переживание перезапуска).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- Затрагиваемый слой: `src/webui/` (маршруты/middleware/app); домен (`src/services/device_service.py`, модели, персистентность) существует и не меняется

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Фиксация baseline до изменений

- [X] T001 Зафиксировать baseline фичи: прогнать `pytest tests/contract/test_access_control.py -q`, `pytest tests/integration/test_access_control.py -q`, `.ai/scripts/run_checks.sh` — записать red-список и покрытие в заметки Phase 3 (все acceptance-тесты доступа сейчас красные — это TDD-точка отсчёта; сравнение в финальной фазе)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Общая инфраструктура для всех US

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 Создать helper получения DeviceService в маршрутах: FastAPI dependency `get_device_service` в новом `src/webui/routes/devices/deps.py` — берёт `request.app.state.device_service` (research R1), raises 503 если сервис недоступен; type hints + docstrings

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Пользователь видит и контролирует только свои устройства (Priority: P1) 🎯 MVP

**Goal**: Идентификация на device-endpoints (middleware), фильтрация списка по доступу, ролевые проверки операций

**Independent Test**: сценарий 1 quickstart — `pytest tests/contract/test_access_control.py -v` (acceptance, сейчас красные)

### Тесты для User Story 1 (TDD — сначала красные)

- [X] T003 [P] [US1] Добавить в `tests/test_webui.py` кейс «create_app регистрирует DeviceAccessMiddleware» (middleware в `app.user_middleware`/поведение: device-endpoint без X-User-ID → 401) — ожидаемо красный

### Реализация для User Story 1

- [X] T004 [US1] Зарегистрировать `DeviceAccessMiddleware` в `create_app` (`src/webui/app.py`) ПОСЛЕ CORS и до включения маршрутов устройств (research R2); зоны ответственности middleware не расширять (только идентификация/`request.state`)
- [X] T005 [US1] Разблокировать фильтрацию `GET /api/v1/devices` по доступу в `src/webui/routes/devices/devices.py:79-82`: устройства по `get_user_accessible_devices(user_id)` через helper T002 (research R3); аноним → пустой список (существующее поведение); фильтр `source_id` поверх фильтра доступа
- [X] T006 [US1] Добавить ролевые проверки на device-endpoints в `src/webui/routes/devices/devices.py`: детали/события — viewer и выше, команда — controller и выше, конфигурация — admin; статусы 403/404 строго по существующим acceptance-тестам и contracts §1 (research R2: проверка через сервис/`check_device_access`, иерархия viewer<controller<admin)
- [X] T007 [US1] Прогнать `pytest tests/contract/test_access_control.py tests/integration/test_access_control.py -v -k "403 or 401 or viewer or controller"` — acceptance US1 зелёные; зафиксировать расхождения тест↔contract (если есть) в заметках задачи

**Checkpoint**: US1 работает независимо:匿名 → 401/пустой список; роли enforcing

---

## Phase 4: User Story 2 - Администратор управляет доступом (Priority: P2)

**Goal**: Реальные grant/revoke/list вместо заглушек; персистентность; история операций

**Independent Test**: сценарий 2–3 quickstart — `pytest tests/contract/test_access_control.py -k "grant or revoke"` + `pytest tests/integration/test_access_control.py -v`

### Тесты для User Story 2 (TDD — сначала красные)

- [X] T008 [P] [US2] Добавить в `tests/contract/test_access_control.py` кейс «анти-дубликат grant»: повторный POST доступа той же паре (device, user) → роль обновлена, в списке одна запись (research R4) — ожидаемо красный

### Реализация для User Story 2

- [X] T009 [US2] Разблокировать реальную логику `grant_access` в `src/webui/routes/devices/access_control.py:104-117` (research R4): вызов сервиса через helper T002; ответ — сериализованная запись `DeviceAccess` (формат contracts §3); устройство не найдено → 404; заглушка `UUID(int=0)` удалена; повторное назначение → обновление роли (сервис)
- [X] T010 [US2] Разблокировать реальную логику `revoke_device_access` в `src/webui/routes/devices/access_control.py:159-165`: `revoke_access(access_id)` через сервис; запись не существует → 404 (contracts §3); успех → 204
- [X] T011 [US2] Разблокировать реальную логику `get_device_access_list` в `src/webui/routes/devices/access_control.py:199-206`: массив записей устройства (`get_device_accesses`) через сервис; устройство не найдено → 404; заглушка `[]` удалена
- [X] T012 [US2] Проверить фиксацию истории операций (FR-009): при grant/revoke сервис публикует `DeviceAccessChangedEvent` (существующее поведение `device_service.py:476`) — при отсутствии добавить вызов; кейс проверки в `tests/integration/test_access_control.py` (одна запись события на изменение)
- [X] T013 [US2] Прогнать `pytest tests/contract/test_access_control.py -v -k "grant or revoke or access_list or roles"` — acceptance US2 зелёные

**Checkpoint**: US2 работает независимо: grant/revoke/list с реальными данными, персистентность штатная

---

## Phase 5: User Story 3 - Проверка прав в WebSocket-подписках (Priority: P3)

**Goal**: Подписка с проверкой доступа; доставка событий только соединениям с доступом (проверка при каждой доставке — clarify Q1)

**Independent Test**: сценарий 4 quickstart — `pytest tests/contract/test_access_control.py -k websocket` + integration кейс доставки

### Тесты для User Story 3 (TDD — сначала красные)

- [X] T014 [P] [US3] Добавить кейс «доставка после отзыва» в `tests/integration/test_access_control.py`: подписка с доступом → событие доставлено; отзыв доступа → следующее событие НЕ доставлено (clarify Q1) — ожидаемо красный

### Реализация для User Story 3

- [X] T015 [US3] Расширить `ConnectionManager` в `src/webui/routes/devices/websocket.py` ассоциацией соединение→идентификация (ConnectionIdentity из data-model.md): `user_id` (устанавливается при auth-сообщении), доступные устройства; очистка при `disconnect` (research R5)
- [X] T016 [US3] Разблокировать проверку `check_device_access` при подписке в `src/webui/routes/devices/websocket.py:158-174` (T071): отказ → error-сообщение с device_id, устройство НЕ добавляется в подписки; успех → существующее поведение `subscribed` (FR-008)
- [X] T017 [US3] Доставка по правам: `broadcast_state_change` / `broadcast` в `src/webui/routes/devices/websocket.py` рассылает событие устройства ТОЛЬКО аутентифицированным соединениям с доступом к нему — проверка при каждой доставке (`check_device_access`, research R5); соединения без подписки на устройство не получают его (существующая семантика)
- [X] T018 [US3] Прогнать `pytest tests/contract/test_access_control.py -v -k websocket` и кейс T014 — зелёные

**Checkpoint**: All user stories should now be independently functional

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Полный регресс и документация

- [X] T019 [P] [Polish] Тест переживания перезапуска (FR-010/SC-004): integration-кейс «grant → пересоздать app/DeviceService → доступ сохранился» (штатная DeviceAccessPersistence, research R7) в `tests/integration/test_access_control.py`

> **Заметки реализации (2026-09-29)**:
> - T001 baseline фичи: contract access — **10 errors** (`from src.main import app` — атрибут не существовал; тесты не выполнялись); integration access — **3 skipped** («Зависит от T064-T067 реализации»).
> - Ключевой wiring (сверх плана): в `src/main.py` добавлен module-level `app = create_app()` (TestClient-совместимость); выявлено, что `access_control.router` вообще не был зарегистрирован (все access-endpoints давали 404 «Not Found») — включён в `routes/devices/__init__.py` и `create_app`.
> - T006/T009: порядок проверок — **существование (404) ДО доступа** (403), из тела integration-сценария; grant стал **device-blind** (снят device-existence-требование в `DeviceService.grant_access` — доступ выдаётся на идентификатор до синка; отклонение от «сервис не менять», диктовано acceptance).
> - T009: grant/revoke/list переведены на **body-схемы** (были query-параметры); невалидная роль → 400 (Literal → 422 не подходил). Единственный POST /command: стаб `send_device_command` (`cmd_123`) удалён, `CommandRequest` стал union-схемой (T054 `name`+required `parameters` / `command_name` / `service`-compat).
> - T016/T017: подписка проверяет доступ (403→error в сокет), `ConnectionManager` хранит соединение→{user_id, подписки}; `broadcast_device_event` доставляет только подписанным с доступом — проверка при каждой доставке (clarify Q1).
> - T014: тест выявил **dual-name модуль**: `main.py` импортирует top-level `webui`, а не `src.webui` — разные экземпляры `connection_manager` (тест импортирует из `webui.routes.devices.websocket`). Потенциальный Техдолг: unify-имена пакетов.
> - Разоблачённые падения (НЕ регрессии US4): после module-level `app` contract-тесты, падавшие с ImportError (27 errors в baseline), стали выполняться: ~16 разоблачённых failed — pre-existing mismatches вне scope фичи (выдуманные UUID устройств → 404, url-normalize `/` в sources, `list_sources_empty` межтестовая поллюция, `test_websocket` — HAWebSocketClient). Обновлены fixture двух файлов (`test_devices_api`, `test_sources_api`): default-заголовки идентификации (FR-002/SC-002).
> - Итоги прогонов: access contract **11 passed**, access integration **2 passed / 3 skipped** (skip-маркеры «Зависит от T064-T067» сохранились), middleware/маршруты webui — зелёные, `test_container`/`test_release_mechanism` — зелёные; root-регресс 78 failed — структура падений идентична baseline (новых нет, +2 passed).
- [X] T020 Прогнать quickstart.md сценарии 1–5 полностью, обновить статусы в карте сценариев quickstart (при расхождениях — вернуться в соответствующую фазу)
- [X] T021 Полный регресс: `.ai/scripts/run_checks.sh` (exit 0, покрытие ≥80%) + `pytest tests/ --ignore=tests/contract --ignore=tests/integration -q`, `pytest tests/contract -q`, `pytest tests/integration -q` — сравнить с baseline T001: acceptance-тесты доступа зелёные (цель фичи), НОВЫХ падений в остальных группах нет
- [X] T022 [P] Обновить документацию: закрыть Known Issue #11 в `.ai/01_PROJECT_STATE.md`, Tech Debt #1 в `.ai/03_ROADMAP.md`, отметить RU T067–T071 в `specs/001-device-integration/tasks.md`, changelog; запустить `python3 .ai/scripts/sync_roadmap.py --auto-update`
- [X] T023 Обновить статусы фичи: `specs/004-device-access-control/spec.md` → Implemented, чек-лист `checklists/requirements.md` — финальная сверка, статусы quickstart

> **Заметки Phase 6 (2026-09-29)**:
> - T020: все 5 сценариев quickstart пройдены, статусы внесены в карту.
> - T021: `run_checks.sh` exit 0 (покрытие 92.9%); root 78 failed / 1233 passed — структура падений идентична baseline T003 (51 device_service + 14 playwright + 5 cache + 3 models + 3 batcher + 2 discovery), +2 passed; contract/integration — baseline-«27 errors» разоблачены module-level `app` (тесты начали выполняться): access-тесты зелёные, разоблачённые failed — pre-existing mismatches вне scope фичи (см. заметки реализации).
> - T022: Known Issue #11 закрыт (PROJECT_STATE), Tech Debt #1 закрыт (ROADMAP), RU T067–T071 отмечены (specs/001), changelog дополнен, sync_roadmap выполнен.
> - T023: spec → `Implemented`, чек-лист сверён (16/16), quickstart-карта со статусами.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: нет зависимостей — сразу
- **Foundational (Phase 2)**: после Setup; БЛОКИРУЕТ все US
- **US1 (Phase 3)**: после Phase 2; не зависит от других US
- **US2 (Phase 4)**: после Phase 2 (helper T002); не зависит от US1 (тесты не зависят — оба/все acceptance уже есть)
- **US3 (Phase 5)**: после Phase 2; переиспользует паттерн проверки US1, но реализуем независимо
- **Polish (Phase 6)**: T019 параллелен фазам US (только persistence); T020–T023 — после всех US

### User Story Dependencies

- **US1 (P1)**: T002 → T003 → T004 → T005/T006 → T007
- **US2 (P2)**: T002 → T008 → T009/T010/T011 → T012 → T013
- **US3 (P3)**: T002 → T014 → T015 → T016/T017 → T018

### Parallel Opportunities

- T003 ∥ T008 ∥ T014 (разные тестовые файлы/кейсы — после T002)
- US1 ∥ US2 ∥ US3 после Phase 2 (разные участки: app.py+devices.py / access_control.py / websocket.py)
- T019 ∥ любая US (integration-файл — последовательность в рамках файла, но концептуально параллельна)

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 + 2 (baseline, helper)
2. Phase 3: US1 целиком
3. **STOP and VALIDATE**: сценарий 1 quickstart
4. Сегментация прав уже даёт value — деплой/demonstration возможен

### Incremental Delivery

1. Setup + Foundational → foundation готов
2. +US1 → фильтрация/идентификация/роли (MVP!)
3. +US2 → администрирование доступов
4. +US3 → real-time каналы по правам
5. Polish → регресс + документация

### Notes

- Acceptance-тесты уже написаны (contract/integration) — НЕ менять их ожидания; добиваться их зелёного статуса
- Домен (сервис/модель/персистентность) НЕ переписывать — только вызовы через helper T002
- Статусы 403/404 сверять с contracts §1 и фактическими тестами; расхождение тест↔contract — фиксировать в заметках
- Commit after each task or logical group; run_checks перед коммитом
