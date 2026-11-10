# Tasks: Health Check дома — единый список проблем

**Input**: Design documents from `specs/019-house-health-check/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/health-api.md`, `quickstart.md`

**Tests**: проект работает по TDD — тесты пишутся до реализации и входят в каждую историю.

**Organization**: задачи сгруппированы по пользовательским историям; каждая история
даёт самостоятельный проверяемый результат.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно делать параллельно (разные файлы, нет зависимостей)
- **[Story]**: US1–US5 из `spec.md`
- Пути файлов указаны точно

## Path Conventions

- Ядро: `src/core/`
- Адаптеры: `src/adapters/`
- Веб: `src/webui/`, `frontend/src/`
- Тесты: `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: модели, конфигурация и хранилище, общие для всех историй.

- [X] T001 [P] Добавить в `src/core/models/manifest_rules.py` поля `check_interval_minutes`, `stale_min_hours`, `battery_low_percent`, `battery_silent_hours`, `command_grace_minutes`, `notification_repeat_hours` в `SensorHealthRules` с валидацией: `battery_low_percent` 0–100, `stale_min_hours >= 1`, `battery_silent_hours >= 24`, `command_grace_minutes >= 1`, `notification_repeat_hours >= 1`; round-trip тест `tests/unit/webui/test_manifest_rules_roundtrip.py`
- [X] T002 [P] Создать `src/core/models/health.py`: enum `ProblemKind` (`stale`, `low_battery`, `battery_silent`, `unavailable`, `missing_entity`, `house_unreadable`, `command_not_applied`, `device_mismatch`, `fsm_stuck`, `ha_disconnected`), `ProblemLevel` (`info`, `warning`, `critical`), dataclass `HouseProblem` с полями из `data-model.md` и валидацией `first_seen <= last_seen`, `closed_at >= first_seen`
- [X] T003 [P] Создать `src/core/persistence/health_store.py`: атомарная запись `health_problems.json` (временный файл + `os.replace`), версия схемы, чтение с предупреждением при повреждении; тесты `tests/unit/core/test_health_store.py`
- [X] T004 [P] Создать `src/core/services/health_registry.py`: открытие/закрытие проблем, `last_seen`, группировка по `subject`, стабильный `fingerprint` (хэш отсортированных `(kind, subject, detail)`), хранение закрытых 30 дней; тесты `tests/unit/services/test_health_registry.py`

**Checkpoint**: модели и хранилище готовы, но обход ещё не использует их.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: подключить реестр к существующему обходу и сводке, не меняя поведения
для старых клиентов.

**⚠️ CRITICAL**: без этого этапа истории не начинать.

- [X] T005 Подключить `HealthStore` и `HealthRegistry` в `src/app/house_services.py` и `src/app/container.py`: загрузка при сборке, передача в `HouseHealthService`, сохранение после каждого обхода; тест `tests/integration/test_health_registry_wiring.py`
- [X] T006 Расширить `compose_report` в `src/core/services/problems.py`: принимать реестр и отдавать `count`, `levels`, `problems` с `id`, `first_seen`, `last_seen`, `reasons`; старый плоский список сохранить; тесты `tests/unit/services/test_problems_compose.py`
- [X] T007 Перевести `HouseHealthService.sweep()` в `src/core/services/house_health.py` на реестр: открывать проблемы, обновлять `last_seen`, закрывать исчезнувшие с `close_reason = recovered`; поведение старых видов проблем не менять; тесты `tests/unit/services/test_house_health_registry.py`
- [X] T008 [P] Добавить конфигурационные значения из `T001` в загрузку `HouseHealthService` (интервал, порог, батарейки, команды, уведомления) с fallback на текущие константы; тест `tests/unit/services/test_health_config.py`

**Checkpoint**: обход по-прежнему работает, но проблемы уже имеют историю и уровни.

---

## Phase 3: User Story 1 — Один экран «Проблемы дома» (Priority: P1) 🎯 MVP

**Goal**: владелец видит все активные проблемы в одном списке и через API.

**Independent Test**: создать проблемы в тестовом адаптере и убедиться, что
`/api/v1/problems` и страница `/problems` показывают их с причиной и временем;
пустой список выглядит как «проблем нет».

### Tests for User Story 1

- [X] T009 [P] [US1] Контрактный тест `GET /api/v1/problems` в `tests/contract/test_health_api.py`: поля `generated_at`, `count`, `levels`, `problems[]`, сортировка `critical → warning → info`
- [X] T010 [P] [US1] Интеграционный тест единого списка в `tests/integration/test_health_problems_api.py`: обход + сторож + неприменённая команда сводятся в один ответ без дублей по `subject`

### Implementation for User Story 1

- [X] T011 [US1] Добавить `GET /api/v1/problems` в `src/webui/routes/health.py`, собирающий `compose_report` из обхода и сторожа; ошибка дома — не 500, а `ha_disconnected` в списке
- [X] T012 [US1] Расширить `GET /api/v1/health` в `src/webui/routes/health.py` полями `count`, `levels`, `problems` (совместимо со старым ответом)
- [X] T013 [P] [US1] Добавить типы `Problem`, `ProblemLevel`, `ProblemReason` в `frontend/src/lib/types.ts`
- [X] T014 [US1] Создать страницу `frontend/src/app/problems/page.tsx`: список проблем, фильтры по уровню и месту, пустое состояние «проблем нет», ссылка на комнату/локацию
- [X] T015 [US1] Расширить `frontend/src/features/home/alerts-panel.tsx`: уровень, причина, `first_seen`, ссылка на `/problems`
- [X] T016 [P] [US1] Vitest-тесты страницы и панели в `frontend/src/features/home/__tests__/` и `frontend/src/app/problems/__tests__/`
- [X] T017 [US1] Добавить журналирование открытия/закрытия проблем в `src/core/services/health_registry.py` (WARNING/INFO, причина и `subject`)

**Checkpoint**: MVP — единый список и API работают, даже если новые пороги ещё не включены.

---

## Phase 4: User Story 2 — Молчащий датчик (Priority: P2)

**Goal**: у каждого датчика свой ожидаемый интервал и порог молчания; событийные
датчики не дают ложных тревог.

**Independent Test**: датчик с историей 10 минут молчит 2 часа → проблема
«молчит» с ожиданием 20 минут; событийный датчик движения не объявляется
молчащим.

### Tests for User Story 2

- [X] T018 [P] [US2] Тест расчёта медианы и fallback в `tests/unit/services/test_health_expectations.py`: 10 интервалов → p50, пустая история → класс, битые события игнорируются
- [X] T019 [P] [US2] Тест порогов в `tests/unit/services/test_house_health_stale.py`: `stale_after = max(2 × p50, 2 ч)`, граница ровно 2 часа, событийные датчики без heartbeat не тревожат
- [X] T020 [P] [US2] Интеграционный тест «пропал датчик» в `tests/integration/test_health_silent_sensor.py`: показание пропало → проблема; вернулось → закрыта

### Implementation for User Story 2

- [X] T021 [US2] Создать `src/core/services/health_expectations.py`: чтение событий из `EventStore` за 7 дней, медиана интервалов, fallback по `device_class`, кэш на обход
- [X] T022 [US2] Использовать `SensorExpectation` в `HouseHealthService._reading`/`_problem` (`src/core/services/house_health.py`): порог на сущность вместо общего 6 часов, исключения для событийных и батарейных датчиков
- [X] T023 [US2] Добавить `EventStore.intervals_since()` в `src/core/persistence/event_store.py` (SQL по `events`, индекс `entity_id` уже есть) и тест `tests/unit/core/test_event_store_intervals.py`
- [X] T024 [US2] Логировать причину порога: «молчит 2.4 ч при ожидании 20 мин (история)» в `src/core/services/house_health.py`

**Checkpoint**: молчание считается по-настоящему, ложные тревоги событийных датчиков исключены.

---

## Phase 5: User Story 3 — Батарейки (Priority: P3)

**Goal**: раз в сутки показывать низкий заряд и молчание батареек.

**Independent Test**: батарейка 15 % → проблема; 35 % → нет; нет отчёта 49 часов →
«батарейка молчит»; новый отчёт → закрыто.

### Tests for User Story 3

- [ ] T025 [P] [US3] Тест низкого заряда в `tests/unit/services/test_health_battery.py`: 15 % → `low_battery`, 20 % → нет (строгое `<`), 35 % → нет
- [ ] T026 [P] [US3] Тест молчания батарейки: 47 часов → нет, 49 часов → `battery_silent`; батарейка не попадает в общий `stale`
- [ ] T027 [P] [US3] Интеграционный тест суточной проверки в `tests/integration/test_health_battery_daily.py`: второй обход в те же сутки не дублирует проблему

### Implementation for User Story 3

- [ ] T028 [US3] Добавить вид `battery_silent` и текст причины в `src/core/services/problems.py`
- [ ] T029 [US3] Реализовать суточную проверку батареек в `src/core/services/house_health.py`: `battery_low_percent`, `battery_silent_hours`, отметка последней проверки в реестре/состоянии
- [ ] T030 [US3] Добавить `battery_watch_entities` и пороги из `SensorHealthRules` в обход через `src/app/house_services.py`; тест конфигурации `tests/unit/services/test_health_config.py`

**Checkpoint**: батарейки видны, но не шумят каждые 15 минут.

---

## Phase 6: User Story 4 — Команда принята, но не применена (Priority: P4)

**Goal**: через 5 минут после команды платформа видит, что прибор не изменился,
и показывает это как проблему, не повторяя команду.

**Independent Test**: подставной прибор принимает команду и не меняет состояние →
`command_not_applied`; меняет → проблемы нет; переходное состояние не считается
провалом.

### Tests for User Story 4

- [ ] T031 [P] [US4] Тест трекера в `tests/unit/core/test_command_expectations.py`: запись, замена новой командой, `applied`, `failed` после допуска, `unknown` при нечитаемом состоянии
- [ ] T032 [P] [US4] Тест сводки: `command_not_applied` попадает в `/api/v1/problems` с прибором, сервисом и временем
- [ ] T033 [P] [US4] Интеграционный тест «принято, но не применено» в `tests/integration/test_health_command_not_applied.py`

### Implementation for User Story 4

- [ ] T034 [US4] Создать `src/core/commands/expectations.py`: `CommandExpectationTracker` с `record`, `pending`, `apply`, `fail`, `clear`, TTL 10 минут; только реально отправленные команды
- [ ] T035 [US4] Подключить трекер в `src/core/commands/dispatcher.py` (после успешной отправки) и в `src/app/container.py`; не записывать заблокированные локкаутом команды
- [ ] T036 [US4] Проверять ожидания в `HouseHealthService.sweep()`: через `command_grace_minutes` сравнить с фактическим состоянием, создать `command_not_applied`, закрыть при совпадении
- [ ] T037 [US4] Исключить переходные состояния (штора `opening`/`closing`, лампа в переходе, климат `HEATING`) из провала; тест на каждый случай
- [ ] T038 [US4] Логировать команду и её судьбу: отправлена, применена, не применена (с прибором и временем) в `src/core/commands/expectations.py` и `src/core/services/house_health.py`

**Checkpoint**: «команда выполнена» больше не значит «прибор сделал».

---

## Phase 7: User Story 5 — Уведомления без спама (Priority: P5)

**Goal**: одно persistent-уведомление Home Assistant, обновляется по изменению
состава, не чаще раза в 24 часа при неизменном составе, снимается при решении.

**Independent Test**: проблема появилась → уведомление; сутки без изменений →
второго нет; новая проблема → обновление; всё решено → снято; перезапуск → без
дубля.

### Tests for User Story 5

- [ ] T039 [P] [US5] Контрактный тест уведомления в `tests/contract/test_health_notification.py`: `notification_id`, заголовок с числом, текст из `summary_text`
- [ ] T040 [P] [US5] Тест антиспама в `tests/unit/services/test_health_notifier.py`: тот же fingerprint → молчание; новый → отправка; 24 часа → одно обновление; пусто → dismiss; HA недоступен → `dirty`
- [ ] T041 [P] [US5] Тест перезапуска в `tests/integration/test_health_notification_restart.py`: `first_seen` сохранён, повторного уведомления нет

### Implementation for User Story 5

- [ ] T042 [US5] Добавить в `src/adapters/home_assistant/notifications.py` методы `create_persistent_notification` и `dismiss_persistent_notification`; в `MockAdapter` — no-op
- [ ] T043 [US5] Создать `src/core/services/health_notifier.py`: fingerprint, `last_sent_at`, `dirty`, `repeat_hours`, вызов через протокол/колбэк (без импорта адаптера)
- [ ] T044 [US5] Подключить notifier в `src/app/house_services.py` к `on_report` обхода и к `_publish_problems`; при изменении состава — обновить, при пустом — снять
- [ ] T045 [US5] Сохранять `NotificationState` в `health_problems.json` через `HealthStore`; восстановление после перезапуска
- [ ] T046 [US5] Логировать уведомления: создано/обновлено/снято, число проблем, причина в `src/core/services/health_notifier.py`

**Checkpoint**: владелец получает одно осмысленное уведомление, а не поток.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: документация, приёмка, качество.

- [ ] T047 [P] Обновить `.ai/01_PROJECT_STATE.md` (логика порогов, уведомления, команды), `.ai/02_ARCHITECTURE.md` (реестр проблем и трекер ожиданий), `.ai/BACKLOG.md` (F6 закрыт)
- [ ] T048 [P] Обновить `docs/` и `README` разделами о `/api/v1/problems` и уведомлении
- [ ] T049 Прогнать `specs/019-house-health-check/quickstart.md` на тестовом стенде: молчащий датчик, батарейка, команда, антиспам, перезапуск, недоступный HA
- [ ] T050 Полный прогон `make test`, `make lint`, `make type-check`, `make check-architecture` по `pyproject.toml`; покрытие новых файлов ≥80 %
- [ ] T051 Пересобрать образ `deploy/docker/docker-compose.prod.yml`, выкатить, проверить `/ready`, `/api/v1/problems`, уведомление в HA, `problem_count`
- [ ] T052 Живая проверка по `specs/019-house-health-check/quickstart.md`: один реальный молчащий/недоступный датчик и одна батарейка; убедиться, что проблема появилась и снялась, уведомление не спамит

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: без зависимостей.
- **Foundational (Phase 2)**: после Setup; блокирует все истории.
- **US1 (Phase 3)**: после Foundational; даёт MVP.
- **US2 (Phase 4)**: после Foundational; использует реестр из US1, но проверяется отдельно.
- **US3 (Phase 5)**: после Foundational; независима от US2.
- **US4 (Phase 6)**: после Foundational; независима от US2/US3.
- **US5 (Phase 7)**: после US1 (нужен fingerprint реестра); может идти параллельно US2–US4.
- **Polish (Phase 8)**: после выбранных историй.

### User Story Dependencies

- **US1 (P1)**: реестр, API, страница. Зависит только от Foundational.
- **US2 (P2)**: ожидаемые интервалы; использует `EventStore` и реестр.
- **US3 (P3)**: батарейки; использует реестр и конфиг.
- **US4 (P4)**: команды; использует реестр и диспетчер.
- **US5 (P5)**: уведомления; использует fingerprint реестра из US1.

### Within Each User Story

- Тесты — первыми, падают до реализации.
- Модели → сервисы → endpoint/UI.
- После каждой истории — самостоятельная проверка и коммит.

### Parallel Opportunities

- T001–T004 (Setup) — параллельно.
- T009/T010, T013/T016 — параллельно внутри US1.
- T018–T020 (US2), T025–T027 (US3), T031–T033 (US4), T039–T041 (US5) — тесты можно писать параллельно.
- US2, US3, US4 можно вести параллельно после Foundational; US5 — после US1.

---

## Parallel Example: User Story 1

```text
Task: "Контрактный тест GET /api/v1/problems в tests/contract/test_health_api.py"
Task: "Интеграционный тест единого списка в tests/integration/test_health_problems_api.py"
Task: "Типы Problem в frontend/src/lib/types.ts"
Task: "Vitest-тесты страницы /problems"
```

## Parallel Example: User Story 2

```text
Task: "Тест медианы и fallback в tests/unit/services/test_health_expectations.py"
Task: "Тест порогов в tests/unit/services/test_house_health_stale.py"
Task: "Интеграционный тест пропавшего датчика"
```

---

## Implementation Strategy

### MVP First (User Story 1)

1. Phase 1 + Phase 2.
2. Phase 3: `/api/v1/problems` и страница `/problems`.
3. Остановиться и проверить: единый список работает на текущем пороге 6 часов.
4. Выкатить MVP.

### Incremental Delivery

1. MVP (US1) → единый список.
2. US2 → настоящие пороги молчания.
3. US3 → батарейки.
4. US4 → неприменённые команды.
5. US5 → уведомления без спама.
6. Polish → документация и живая приёмка.

### Notes

- [P] — разные файлы, нет зависимостей.
- Каждая история заканчивается коммитом `test`/`fix`/`docs` по правилам проекта.
- Не менять FSM, debounce и таймеры (конституция I).
- Автоматический ремонт не входит: только наблюдение и сообщение.
- Все пороги — в манифесте; значения в коде только fallback.
