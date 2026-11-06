---
description: "Task list for architecture hardening"
---

# Tasks: Архитектурная гигиена и чистые границы

**Input**: Design documents from `/specs/018-architecture-hardening/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: включены — конституция проекта требует TDD (принцип II). В каждом
срезе тесты пишутся первыми и должны падать до реализации.

**Organization**: задачи сгруппированы по пользовательским историям; каждый
срез можно реализовать, проверить и выпустить отдельно.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно выполнять параллельно (разные файлы, нет зависимостей)
- **[Story]**: к какой истории относится задача
- У каждой задачи указан точный путь к файлу

## Path Conventions

Модульный монолит: `src/`, `tests/`, `frontend/`, `deploy/`, `tools/` в корне
репозитория.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: базовая линия и инструменты, без которых нельзя менять код безопасно

- [X] T001 Зафиксировать baseline в `specs/018-architecture-hardening/baseline.md`: полный прогон (3418/19), покрытие 84 %, размеры крупнейших файлов, матрица импортов
- [X] T002 [P] Создать `tests/architecture/__init__.py` и `tests/architecture/ast_helpers.py` — разбор AST для проверок импортов и размеров
- [X] T003 [P] Создать `tests/architecture/allowlist.py` — явные исключения для существующих крупных файлов и временных нарушений, с причиной и сроком
- [X] T004 [P] Создать `tools/dead_code_inventory.py` — поиск модулей и публичных функций без production-вызовов
- [X] T005 [P] Добавить в `Makefile` цель `check-architecture` и включить её в `check-fast`

**Checkpoint**: baseline зафиксирован, проверки архитектуры запускаются локально.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: общие примитивы для границы управления и контрактов отказов

**⚠️ CRITICAL**: срезы US1–US6 начинаются после этой фазы.

- [X] T006 [P] Создать `src/core/errors.py`: классы ожидаемого отказа, дефекта и аварии, не зависящие от FastAPI
- [X] T007 [P] Создать `src/webui/security/identity.py`: протокол участника (subject, roles, source, trusted) без доверия заголовкам клиента
- [X] T008 [P] Создать `src/webui/middleware_request_id.py`: сквозной `trace_id` для запроса, журнала и ответа
- [X] T009 [P] Создать `tests/unit/core/test_error_taxonomy.py`: три класса отказов различимы и не маскируют друг друга
- [X] T010 [P] Создать `tests/architecture/test_baseline.py`: проверка, что архитектурные тесты входят в общий прогон и не отключены

**Checkpoint**: общие примитивы готовы; можно начинать US1, US2 и US3 параллельно.

---

## Phase 3: User Story 1 — Одно описание дома (Priority: P1) 🎯 MVP

**Goal**: каноническая модель — единственный источник проверки, редактирования и исполнения.

**Independent Test**: добавить новое поле, сохранить штатным путём, перезапустить платформу и увидеть значение в работе; неверное значение отклоняется с путём до поля.

### Tests for User Story 1 (написать первыми, убедиться, что падают)

- [X] T011 [P] [US1] Contract-тест round-trip всех полей в `tests/contract/test_manifest_roundtrip.py`
- [X] T012 [P] [US1] Unit-тест неизвестных полей и `extensions` в `tests/unit/core/test_manifest_unknown_fields.py`
- [X] T013 [P] [US1] Unit-тест сохранения через `PUT /api/v1/manifest` канонической моделью в `tests/unit/webui/test_manifest_save_canonical.py`
- [X] T014 [P] [US1] Тест совместимости манифеста прежней версии в `tests/contract/test_manifest_backward_compat.py`

### Implementation for User Story 1

- [X] T015 [US1] Задать `extra="forbid"` и явное пространство расширений в `src/core/models/manifest.py`
- [X] T016 [US1] Перевести `src/core/persistence/manifest_store.py` на каноническую модель по умолчанию; убрать параметр второй модели
- [X] T017 [US1] Удалить доменные дубли из `src/webui/models.py`: оставить только DTO и view-модели
- [X] T018 [US1] Обновить `src/webui/app.py`, `src/webui/__init__.py`, `src/webui/routes/overview.py` под каноническую модель
- [X] T019 [US1] Перевести `src/webui/routes/manifest.py` на `Manifest.model_json_schema()` и единые ошибки полей
- [X] T020 [US1] Удалить `src/core/manifest_schema.py` и `src/core/manifest_validator.py`; перенести нужные проверки в модель
- [X] T021 [US1] Удалить или переписать тесты `tests/test_manifest_schema.py`, `tests/test_manifest_validator.py`, `tests/unit/webui/test_manifest_model_roundtrip.py`
- [X] T022 [US1] Обновить документацию модели: `.ai/02_ARCHITECTURE.md`, `specs/018-architecture-hardening/data-model.md`
- [X] T023 [US1] Проверить сценарии `quickstart.md` для Wave A и зафиксировать результат в `specs/018-architecture-hardening/quickstart.md`

**Checkpoint**: описание дома имеет один источник; US1 можно выпускать отдельно.

---

## Phase 4: User Story 2 — Граница управления (Priority: P1)

**Goal**: default deny для изменяющих операций; серверная идентичность; подделанный админ не работает.

**Independent Test**: матрица запросов «аноним / гость / владелец / ingress» ко всем изменяющим операциям; allowlist состояния доступен.

### Tests for User Story 2

- [X] T024 [P] [US2] Contract-тест матрицы доступа в `tests/contract/test_management_auth.py`
- [X] T025 [P] [US2] Contract-тест подделанных `X-User-ID`/`X-Is-Admin` в `tests/contract/test_management_auth.py`
- [X] T026 [P] [US2] Тест allowlist `/health`, `/ready`, `/metrics` в `tests/contract/test_management_auth.py`
- [X] T027 [P] [US2] Тест проверки `Origin`/`Referer` для изменяющих запросов из браузера в `tests/contract/test_same_origin.py`

### Implementation for User Story 2

- [X] T028 [US2] Реализовать `src/webui/security/identity.py`: роль по доверенному источнику, ingress только из доверенного прокси, заголовки клиента не повышают права
- [X] T029 [US2] Реализовать `src/webui/security/network.py`: разбор доверенных подсетей и проверка адреса запроса
- [X] T030 [US2] Создать глобальный `src/webui/middleware_auth.py` с default deny и явным allowlist
- [X] T031 [US2] Подключить middleware в `src/webui/app.py`; убрать доверие заголовкам в `src/webui/middleware_access_control.py`
- [X] T032 [US2] Защитить `src/webui/routes/manifest.py`, `src/webui/routes/dashboard.py`, `src/webui/routes/devices/*.py`
- [X] T033 [US2] Перевести `src/webui/routes/session.py` на источник и роль (без входа/пароля)
- [X] T034 [US2] Обновить `frontend/src/lib/api.ts`: обработка 403 и понятное сообщение «управление доступно только из домашней сети»
- [X] T035 [US2] Писать отказы доступа в журнал с источником, операцией, причиной и `trace_id`
- [X] T036 [US2] Обновить `deploy/docker/.env.example` и `deploy/README.md`: доверенные подсети, отказ по умолчанию, остаточный риск LAN
- [X] T037 [US2] Проверить сценарии `quickstart.md` для Wave B и зафиксировать результат

**Checkpoint**: ни одна изменяющая операция не доступна анонимно; состояние — по allowlist.

---

## Phase 5: User Story 3 — Воспроизводимая поставка (Priority: P2)

**Goal**: одинаковый коммит даёт одинаковый набор зависимостей; уязвимости блокируют выпуск; runtime без root и компиляторов.

**Independent Test**: две чистые сборки совпадают; подложенная уязвимость блокируется; образ запускается без root.

### Tests for User Story 3

- [X] T038 [P] [US3] Тест отсутствия плавающих базовых образов и root в `tests/contract/test_image_hardening.py`
- [X] T039 [P] [US3] Тест наличия lock-файла и запрета `>=` без фиксации в `tests/contract/test_dependency_lock.py`
- [X] T040 [P] [US3] Скрипт проверки воспроизводимости в `tools/check_reproducible_build.py`

### Implementation for User Story 3

- [X] T041 [US3] Ввести `uv` и `uv.lock`; перевести установку на `uv sync --frozen` в `pyproject.toml`, `Makefile`, `deploy/docker/Dockerfile`
- [X] T042 [US3] Переписать `deploy/docker/Dockerfile`: multi-stage runtime, non-root пользователь, без gcc/libffi-dev
- [X] T043 [US3] Захарднить `deploy/docker/docker-compose.prod.yml`: `read_only`, `tmpfs`, `cap_drop: ALL`, `no-new-privileges`, лимиты
- [X] T044 [US3] Закрепить базовые образы по digest в `deploy/docker/Dockerfile`
- [X] T045 [US3] Добавить `pip-audit`, Trivy и SBOM в `.github/workflows/security.yml`
- [X] T046 [US3] Добавить Docker-экосистему в `.github/dependabot.yml`
- [X] T047 [US3] Сделать ворота выпуска: блокировка при critical/high и при отсутствии lock
- [X] T048 [US3] Обновить `deploy/README.md` и `specs/018-architecture-hardening/contracts/build-artifact.md`
- [X] T049 [US3] Проверить сценарии `quickstart.md` для Wave C и зафиксировать результат

**Checkpoint**: сборка воспроизводима, уязвимости видны, образ минимален.

---

## Phase 6: User Story 4 — Локальность изменения (Priority: P2)

**Goal**: ядро не зависит от адаптеров; крупные модули разделены за фасадами; изменение локально.

**Independent Test**: `tests/architecture` падает при импорте `core → adapters`; публичное поведение не меняется; полный прогон зелёный.

**Dependencies**: завершить US1 (каноническая модель) до разделения движка; US2 — до переноса composition root.

### Tests for User Story 4

- [X] T050 [P] [US4] Тест запрета `core → adapters/webui/services` в `tests/architecture/test_dependency_rules.py`
- [X] T051 [P] [US4] Тест отсутствия параллельных доменных моделей в `tests/architecture/test_no_parallel_models.py`
- [X] T052 [P] [US4] Тест бюджета размера модулей в `tests/architecture/test_module_size.py`
- [X] T053 [P] [US4] Тест публичного контракта фасадов до/после разделения в `tests/unit/core/test_engine_facade.py`

### Implementation for User Story 4

- [X] T054 [US4] Вынести composition root из `src/core/container.py` в `src/app/container.py`; обновить `src/main.py`, `src/bootstrap.py`
- [X] T055 [US4] Разделить `src/adapters/ha_adapter.py`: transport, команды, dashboards, discovery, manual events; оставить фасад
- [X] T056 [US4] Разделить `src/core/fsm/engine.py`: переходы, guard/action, таймеры, решения; оставить фасад
- [X] T057 [US4] Вынести фабрики из `src/app/container.py` в `src/app/factories.py`
- [X] T058 [US4] Разделить `src/services/watchdog.py` и `src/services/device_service.py` по ответственностям
- [ ] T059 [US4] Обновить allowlist в `tests/architecture/allowlist.py`: сократить крупные файлы не менее чем на 50 %
- [X] T060 [US4] Включить `pytest tests/architecture` в `.github/workflows/ci.yml` и `Makefile`
- [X] T061 [US4] Обновить `.ai/02_ARCHITECTURE.md` и `specs/018-architecture-hardening/contracts/dependency-rules.md`
- [X] T062 [US4] Проверить сценарии `quickstart.md` для Wave D и зафиксировать результат

**Checkpoint**: конституция IV соблюдается автоматически; крупные модули разделены.

> **Статус US4 на 05.11.2026:** выполнены T050–T058 и T060–T062.
> Composition root перенесён в `src/app/`, добавлены исполняемые проверки
> зависимостей/моделей/размеров, `PlatformContext` вынесен в `src/app/context.py`.
> `HAAdapter` разделён полностью: панели, команды, единицы, discovery, ручные
> события и WebSocket-транспорт в отдельных модулях; **2431 → 1249 строк**.
> `FSMEngine` разделён: таймеры, публикация, журнал решений, guard, action и
> переходы в отдельных модулях; **1982 → 576 строк**.
> Фабрики вынесены из `Container` в `src/app/factories.py`;
> **1602 → 1308 строк**.
> `DeviceService` разделён: доступ, команды, события, кэш и состояния в
> отдельных mixin-модулях; **1475 → 572 строки**.
> `WatchdogService` разделён: жизненный цикл, проверки, повтор решений и
> проблемы в отдельных модулях; **1242 → 302 строки**.
> Модели снимка сторожа вынесены в `src/services/watchdog_models.py`.
> В T059 `MetricsCollector` разделён: определения, FSM/сторож, события и
> устройства в отдельных модулях; **961 → 231 строка**.
> `SimpleHAWebSocketClient` разделён: фильтры, доставка событий, соединение и
> числовые помощники; **923 → 300 строк**.
> `FSMFactory` разделён: модели, загрузка шаблонов и создание из манифеста;
> **857 → 115 строк**.
> Осталось: `container.py`, `manifest.py`, `webui/routes/devices/devices.py`.

---

## Phase 7: User Story 5 — Видимые отказы и контракты (Priority: P2)

**Goal**: ожидаемый отказ, дефект и авария различимы; у внешних операций единый контракт.

**Independent Test**: три класса событий дают разные каналы и причины; ошибка любого маршрута имеет единый формат и `trace_id`.

**Dependencies**: US2 (middleware и identity), US4 (границы и фасады).

### Tests for User Story 5

- [ ] T063 [P] [US5] Contract-тест единого конверта ошибки в `tests/contract/test_error_contract.py`
- [ ] T064 [P] [US5] Unit-тест классификации отказов в `tests/unit/core/test_failure_taxonomy.py`
- [ ] T065 [P] [US5] Тест корреляции `trace_id` от события до ответа в `tests/contract/test_trace_correlation.py`
- [ ] T066 [P] [US5] Тест JSON-режима журнала в `tests/unit/core/test_structured_logging.py`

### Implementation for User Story 5

- [ ] T067 [US5] Расширить `src/core/errors.py`: ожидаемый отказ, дефект, авария; маппинг в HTTP-коды
- [ ] T068 [US5] Ввести DTO ответов и `response_model` для `src/webui/routes/manifest.py`, `devices`, `locations`, `health`
- [ ] T069 [US5] Ввести единый обработчик ошибок в `src/webui/errors.py` и подключить в `src/webui/app.py`
- [ ] T070 [US5] Добавить JSON-режим журнала и обязательные поля корреляции в `src/core/logging_setup.py`
- [ ] T071 [US5] Заменить широкие `except Exception` на границах на классифицированные; оставить широкие только там, где это обосновано
- [ ] T072 [US5] Обновить `specs/018-architecture-hardening/contracts/api-responses.md` и `quickstart.md`
- [ ] T073 [US5] Проверить сценарии `quickstart.md` для Wave E и зафиксировать результат

**Checkpoint**: отказы различимы, контракты описаны, журнал коррелирован.

---

## Phase 8: User Story 6 — Чистота и документация (Priority: P3)

**Goal**: мёртвый код удалён или помечен; документация соответствует коду.

**Independent Test**: у каждого production-модуля есть вызов или пометка «экспериментально»; Known Issues/Roadmap/BACKLOG совпадают с кодом.

**Dependencies**: US1, US3, US4 (после удаления параллельных схем и разделения).

- [ ] T074 [P] [US6] Прогнать `tools/dead_code_inventory.py` и сохранить отчёт в `specs/018-architecture-hardening/dead-code.md`
- [ ] T075 [P] [US6] Удалить legacy `src/bootstrap.py` или свести к вызову `src/app/container.py`
- [ ] T076 [P] [US6] Удалить `src/services/backup_service.py` и `tests/test_backup_service.py`; оставить `deploy.sh backup` как единственный путь
- [ ] T077 [P] [US6] Удалить или пометить неиспользуемые guard'ы в `src/core/guards/context.py`, `src/core/guards/builtin.py`, `src/features/CONTRACT.yaml`
- [ ] T078 [P] [US6] Объединить CLI-деревья `src/cli/health_check.py` и `src/smart_home/cli/`
- [ ] T079 [P] [US6] Пометить `ConfigWatcher` экспериментальным: условие включения, риски, тесты, документация
- [ ] T080 [US6] Синхронизировать `Known Issues`, `.ai/03_ROADMAP.md`, `.ai/BACKLOG.md` с фактическим кодом
- [ ] T081 [US6] Проверить сценарии `quickstart.md` для Wave F и зафиксировать результат

**Checkpoint**: состояние кода однозначно; документация не врёт.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T082 [P] Обновить `.ai/02_ARCHITECTURE.md`: целевые границы, composition root, правила зависимостей
- [ ] T083 [P] Добавить в `README.md`/`CONTRIBUTING.md` правила архитектуры и проверки
- [ ] T084 Прогнать полный набор: `pytest -q`, `ruff check`, `ruff format --check`, `mypy src`
- [ ] T085 Включить coverage-gate не ниже 84 % в `pyproject.toml`/CI
- [ ] T086 Проверить `quickstart.md` целиком и отметить выполненные сценарии
- [ ] T087 Пересобрать образ, проверить `/ready`, `problems: 0`, отсутствие регрессий поведения
- [ ] T088 Обновить `specs/018-architecture-hardening/spec.md`: статус срезов и фактические результаты

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: без зависимостей.
- **Foundational (Phase 2)**: после Setup; блокирует все истории.
- **US1, US2, US3 (Phase 3–5)**: после Foundational; независимы друг от друга.
- **US4 (Phase 6)**: после US1 и US2.
- **US5 (Phase 7)**: после US2 и US4.
- **US6 (Phase 8)**: после US1, US3, US4.
- **Polish (Phase 9)**: после всех выбранных историй.

### User Story Dependencies

- **US1 (P1)**: независима; MVP.
- **US2 (P1)**: независима; может идти параллельно с US1.
- **US3 (P2)**: независима; может идти параллельно с US1/US2.
- **US4 (P2)**: опирается на каноническую модель US1 и middleware US2.
- **US5 (P2)**: опирается на US2 и US4.
- **US6 (P3)**: завершает, опирается на US1/US3/US4.

### Within Each User Story

- Тесты пишутся первыми и падают до реализации.
- Модели → сервисы → маршруты/интерфейс → интеграция.
- После каждого шага — полный прогон затронутых тестов.
- История считается закрытой только после `quickstart.md` для её волны.

### Parallel Opportunities

- Setup: T002–T005 параллельны.
- Foundational: T006–T010 параллельны.
- US1: тесты T011–T014 параллельны; реализация T015–T022 — последовательно по файлам.
- US2: тесты T024–T027 параллельны; реализация T028–T037 — последовательно.
- US3: тесты T038–T040 параллельны; реализация T041–T049 — последовательно.
- US4: тесты T050–T053 параллельны; T055–T058 можно делить по модулям после T054.
- US5: тесты T063–T066 параллельны; реализация T067–T073 — последовательно.
- US6: T074–T079 параллельны после инвентаризации.

---

## Parallel Example: User Story 1

```bash
# Тесты US1 — параллельно:
Task: "Contract-тест round-trip всех полей в tests/contract/test_manifest_roundtrip.py"
Task: "Unit-тест неизвестных полей в tests/unit/core/test_manifest_unknown_fields.py"
Task: "Unit-тест сохранения через PUT в tests/unit/webui/test_manifest_save_canonical.py"

# После тестов — реализация:
Task: "extra=forbid в src/core/models/manifest.py"
Task: "Перевести ManifestStore на каноническую модель"
Task: "Удалить дубли из src/webui/models.py"
```

## Parallel Example: User Stories 1–3

```bash
# После Foundational три среза могут идти одновременно:
Agent A: US1 — канонический манифест
Agent B: US2 — граница управления
Agent C: US3 — воспроизводимая поставка
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Setup + Foundational.
2. US1: канонический манифест.
3. **STOP and VALIDATE**: round-trip, ошибки полей, совместимость.
4. Выпуск: поведение дома не меняется, риск потери поля исчезает.

### Incremental Delivery

1. US1 → проверка → выпуск.
2. US2 → матрица доступа → выпуск (осторожно: меняется вход в интерфейс).
3. US3 → воспроизводимая сборка → выпуск.
4. US4 → границы и разделение → выпуск.
5. US5 → контракты и отказы → выпуск.
6. US6 → чистота и документация → финальный выпуск.

### Parallel Team Strategy

Один разработчик / агент: последовательно US1 → US2 → US3 → US4 → US5 → US6.
Несколько исполнителей: US1, US2, US3 параллельно после Foundational; US4 — после US1+US2; US5 — после US2+US4; US6 — в конце.

---

## Notes

- [P] — разные файлы, нет зависимостей.
- [USn] — трассировка к истории из `spec.md`.
- После каждой задачи или логической группы — коммит.
- Поведение автоматики дома — эталон: регрессия поведения блокирует выпуск.
- Решения владельца (backup, LAN-пароль) не блокируют US1–US5, но нужны к US6.
