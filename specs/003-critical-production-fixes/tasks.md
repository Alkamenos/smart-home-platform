# Tasks: Критические продакшен-фиксы (Phase 9.8)

**Input**: Design documents from `/specs/003-critical-production-fixes/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/operational-contracts.md](contracts/operational-contracts.md), [quickstart.md](quickstart.md)

**Tests**: Включены — требуется явно (FR-014 спецификации + конституция TDD). Тесты пишутся ДО реализации и сначала падают.

**Organization**: Задачи сгруппированы по пользовательским историям (US1/US2/US3) для независимой реализации и тестирования.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно выполнять параллельно (разные файлы, нет зависимостей от невыполненных задач)
- **[Story]**: пользовательская история (US1, US2, US3)

---

## Phase 1: Setup

**Purpose**: общая подготовка перед фиксами

- [X] T001 Подготовить пакет тестов `tests/cli/`: создать `tests/cli/__init__.py` (по конвенции `tests/unit/__init__.py`) и убедиться, что `pytest tests/cli` собирается
- [X] T002 [P] Убедиться, что Docker-окружение готово для верификации: `docker info` OK, каталог `deploy/docker/` содержит `Dockerfile` и `docker-compose.prod.yml` (результат — заметка для задач US1; ничего не коммитить)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: зафиксировать исходное состояние до изменений — чтобы любой регресс в US1–US3 был атрибутируем

**⚠️ CRITICAL**: без baseline все последующие «регрессии» будут неотличимы от pre-existing падений

- [X] T003 Запустить `.ai/scripts/run_checks.sh` и порознь `pytest tests/ --ignore=tests/contract --ignore=tests/integration -q`, `pytest tests/contract -q`, `pytest tests/integration -q`; зафиксировать текущие результаты (покрытие, число падений) в заметках — сравнение пойдёт в Phase 6

> **Baseline 2026-09-29**: `run_checks.sh` exit 0 (покрытие 92.8%); root+unit: **79 failed / 1207 passed** (из них 51 `unit/test_device_service` — межтестовая поллюция: изолированно 1f/62p; 14 `test_webui_playwright` — pre-existing; 5 cache, 3 models, 3 batcher, 2 discovery, 1 metrics); `tests/contract`: 6 failed / 8 passed / 27 errors; `tests/integration`: 4 failed / 6 passed / 9 skipped. Полные списки: `/tmp/shp-baseline/root.txt`.

---

## Phase 3: User Story 1 (P1) — Контейнер запускается и проходит healthcheck

**Goal**: оператор разворачивает платформу одной командой, контейнер healthy, SIGTERM — graceful

**Independent Test**: сценарии 1, 4, 5 из quickstart.md — unit healthcheck-модуля + фактические `docker build` / `compose up` / `stop`

### Тесты (TDD — сначала падающие)

- [X] T004 [US1] Написать тесты healthcheck-модуля в `tests/cli/test_health_check.py`: (а) проба к живому серверу с `/health` → exit 0; (б) недоступный порт → exit 1; (в) таймаут → exit 1; (г) не-200 → exit 1; (д) порт из `WEBUI_PORT`, дефолт 8125. Ожидаемо: падают, модуля нет
- [X] T005 [US1] Обновить тест маршрута в `tests/test_webui.py`: `GET /health` → 200 и JSON `{"status": "ok"}` (Content-Type `application/json`). Ожидаемо: падает (сейчас HTML)

### Реализация

- [X] T006 [US1] Создать `src/cli/health_check.py` по контракту contracts/operational-contracts.md §1: HTTP-проба `http://127.0.0.1:{WEBUI_PORT|8125}/health`, таймаут ≤5с, exit 0 при 200 / exit 1 иначе, одна строка диагностики в stdout, без цикла
- [X] T007 [US1] Изменить маршрут `/health` в `src/webui/routes/__init__.py:37`: JSON-ответ `{"status": "ok"}`, статус 200 (заменить HTML-контент, путь не менять)
- [X] T008 [US1] Прогнать `pytest tests/cli/test_health_check.py tests/test_webui.py -k "health or Health" -v` — все зелёные

### E2E-верификация (сценарии 4–5 quickstart)

- [X] T009 [US1] Выполнить quickstart сценарий 4: `docker build -f deploy/docker/Dockerfile -t smart-home-platform:003 .` → `docker compose -f deploy/docker/docker-compose.prod.yml up -d` → `ps` (ожидаем healthy) → `curl -fsS http://localhost:8125/health` → наблюдение 10 мин без перезапусков. Результат зафиксировать в заметках задачи
- [X] T010 [US1] Если шаг T009 упал на сборке/запуске — исправить `deploy/docker/Dockerfile`/`src/main.py` строго по фактической ошибке (фиксировать только наблюдаемое; enhancement 20 частично устарел — не вносить его гипотезы заранее)
- [X] T011 [US1] Выполнить quickstart сценарий 5: `docker compose ... stop` → в логах нет `Traceback`/`Unclosed client session`, останов ≤30с; при нарушении — дофиксировать graceful shutdown в `src/main.py`

> **Результаты E2E (2026-09-29)**:
> - T009: сборка OK (образ `smart-home-platform:003`), `behavioral-platform` Up **16 мин**, `healthy`, **0 рестартов**, `GET /health` → 200, в логах 0 `Traceback`/`Unclosed` — 10-минутное наблюдение пройдено.
> - T010: не понадобился — T009 прошёл без ошибок сборки/запуска.
> - T011: `docker compose stop` — останов **1с** (≤30с ✓), `Traceback`/`Unclosed client session` — 0 ✓. Наблюдение: uvicorn вывел `Task was destroyed but it is pending` (Task-169 `Server.shutdown()` при закрытии event loop) — критерии не нарушает, вынесено в Known Issues (низкий приоритет).

---

## Phase 4: User Story 2 (P1) — Автовосстановление связи с Home Assistant

**Goal**: каждый обрыв детектируется и восстанавливается автоматически; обрывы видны в логах и метрике; нет утечек задач

**Independent Test**: сценарий 2 из quickstart.md — `pytest tests/test_ha_adapter_reconnect.py -v` (сам цикл уже в коде — тесты его фиксируют и защищают от регрессий)

### Тесты (TDD)

- [X] T012 [US2] Написать `tests/test_ha_adapter_reconnect.py` (4 сценария research R6): (1) mock-клиент с завершающимся `_listen_task` → повторный `connect()` адаптера; (2) порядок backoff 1→2→4→…≤60с и сброс до 1с после успеха (monkeypatch времени/ожидания); (3) shutdown во время задержки → мгновенный выход, после прогона `asyncio.all_tasks()` не содержит «висящих» задач адаптера; (4) `connected=False` + завершённый listen_task = новая попытка. Ожидаемо: часть падает (не всё покрыто), часть — фиксирует существующее поведение

> T012 выполнен: 6 тестов (4 сценария R6 + метрика + логирование). До реализации падали 3 (backoff-фильтрация, метрика, лог), 3 фиксировали существующее поведение; после T013–T015 — все зелёные.

### Реализация остатка

- [X] T013 [US2] Доработать `src/adapters/ha_adapter.py` по результатам T012: при reconnect закрывать старую сессию/клиент и сбрасывать их ресурсы (п.2 enhancement 21), убедиться, что `_listen_loop` в `SimpleHAWebSocketClient` не глушит ошибки молча (при ошибке: `connected=False`, warning, выход — детект обрыва)
- [X] T014 [US2] Добавить метрику `websocket_disconnects_total` (Counter, prometheus_client через инфраструктуру `src/services/metrics_server.py`): ленивая регистрация + инкремент на каждой потере соединения в `src/adapters/ha_adapter.py` (ветка «WebSocket lost»/начало попытки); путь правок: `src/adapters/ha_adapter.py`, `src/services/metrics_server.py`
- [X] T015 [US2] Проверить логирование по contracts §4: WARNING об обрыве с номером попытки и задержкой, INFO об успехе со сбросом backoff — при отсутствии добавить в `src/adapters/ha_adapter.py`
- [X] T016 [US2] Прогнать `pytest tests/test_ha_adapter_reconnect.py tests/test_ha_adapter.py -v` — все зелёные, утечек задач нет

> **Заметки US2 (2026-09-29)**:
> - T013: закрытие сессии/клиента при реконнекте уже обеспечивалось `_cleanup_websocket()` в `finally`; добавлены гвард повторного `connect()` (закрытие старого ws, сброс `_msg_id`/`_handlers`/`_event_handler`) и незамалчивание ошибок в `_listen_loop` (warning на обрыв цикла и на ошибку обработки сообщения).
> - T014: фактический путь правок — `src/core/metrics.py` (счётчик и `record_websocket_disconnect()` в `MetricsCollector` — та самая инфраструктура, которую использует `metrics_server.py`; отдельные правки `metrics_server.py` не потребовались) + инкремент из `ha_adapter._record_disconnect` по факту потери (не при ошибках первичного подключения). Импорт метрик в `ha_adapter` ленивый — модульный импорт создавал цикл `core.container → ha_adapter → src.core`. Попутно исправлен pre-existing баг `initialize()` в `src/core/metrics.py`: 13× `help=` (невалидный kwarg для prometheus_client → `TypeError` до `_initialized = True`, все метрики были no-op); `tests/test_metrics.py` теперь 17 passed (baseline: 1 failed).
> - T015: после обрыва — единый backoff-слой (задержка 1→2→4…≤60с после cleanup, вариант A): WARNING `WebSocket lost (...), reconnecting (attempt N, delay X.Xs)` + INFO `... backoff reset` после успеха; для не-сетевых исключений добавлен `logger.exception` (contracts §4).
> - T016: `pytest tests/test_ha_adapter_reconnect.py tests/test_ha_adapter.py tests/test_metrics.py tests/test_prometheus_metrics.py` → **78 passed, 0 failed**; утечек задач нет (см. `test_stop_during_backoff_is_immediate_and_leaves_no_hanging_tasks`).

---

## Phase 5: User Story 3 (P2) — «Забытые» командные интенты освобождаются автоматически

**Goal**: устройство не блокируется навсегда; force-release логируется; семантика приоритетов сохранена

**Independent Test**: сценарий 3 из quickstart.md — `pytest tests/test_dispatcher_ttl.py -v`

**Зависимость**: lifecycle-правки (T023) требуют `PlatformContext` — не блокирует US1/US2, можно выполнять параллельно им

### Тесты (TDD — сначала падающие)

- [X] T017 [P] [US3] Написать `tests/test_dispatcher_ttl.py` (6 пунктов research/data-model): (1) интент с `ttl_seconds=0.05` после `_cleanup_expired()` освобождает устройство, новый intent проходит; (2) `refresh()` продлевает жизнь; (3) конкурентные `submit()` из двух корутин без гонок (`asyncio.Lock`); (4) preempt по приоритету работает как раньше; (5) force-release пишет WARNING формата из contracts §4 (`device_id`, `source`, минуты, подсказка про `release()` в FSM); (6) `start()` идемпотентен, `stop()` не оставляет задач. Ожидаемо: падает целиком (TTL не реализован)
- [X] T018 [P] [US3] Написать тест регрессии существующего поведения диспетчера: расширить `tests/test_dispatcher.py` кейсом «intent без истечения живёт дольше cleanup-интервала — не освобождается» (защита от ложных срабатываний, SC-005)

### Модель и логика (`src/core/commands/dispatcher.py`)

- [X] T019 [US3] Расширить `CommandIntent` в `src/core/commands/dispatcher.py`: поля `last_updated: float = time.time()`, `ttl_seconds: float = 3600.0` с валидацией **«ttl_seconds >= 0 (значение 0 допустимо — немедленное истечение)»** (data-model.md); методы `refresh()` и `is_expired() -> bool` (`time.time() - last_updated > ttl_seconds`); type hints + docstrings (Google style)
- [X] T020 [US3] Добавить в `CommandDispatcher.__init__` параметр `cleanup_interval: float = 300.0` и поле `_lock: asyncio.Lock`; охватить `_active_intents` блокировкой в `submit()` и `release()` (FR-011)
- [X] T021 [US3] В `submit()` при успешном захвате и повторном захвате тем же intent вызывать `intent.refresh()`; при вытеснении по приоритету логировать preempt (существующее поведение сохранить)
- [X] T022 [US3] Реализовать cleanup: `start()` (идемпотентный `asyncio.create_task(self._cleanup_loop())`), `stop()` (cancel + await с подавлением `CancelledError`), `_cleanup_loop()` (сон `cleanup_interval`, выход по `stop()`), `_cleanup_expired()` — под `self._lock` удалить все `is_expired()` и для каждого WARNING из contracts §4: `TTL EXPIRED: force-releasing {device_id} (source={intent.source}, idle {N:.0f} min) — possible missing release() in FSM`

### Lifecycle

- [X] T023 [US3] Подключить lifecycle: `src/core/container.py` — `dispatcher.start()` после создания диспетчера в `build()` и асинхронный `shutdown()` на `PlatformContext` (останов диспетчера, идемпотентно); `src/main.py` — в `finally` после `server.serve()` вызывать `ctx.shutdown()` (без дублирования уже имеющихся `adapter.stop()`/`fsm.shutdown()` — объединить в одну идемпотентную цепочку)

### Верификация

- [X] T024 [US3] Прогнать `pytest tests/test_dispatcher_ttl.py tests/test_dispatcher.py -v` — все зелёные

> **Заметки US3 (2026-09-29)**:
> - T017: `tests/test_dispatcher_ttl.py` — 10 тестов (6 пунктов R4/data-model + is_expired/валидация ttl≥0/refresh-интеграция); до реализации 10 failed / 13 passed, после — все зелёные.
> - T020: `asyncio.Lock` охватывает критические секции `submit()` и `_cleanup_expired()`; `release()` **остался синхронным** (вызывается из синхронного FSM action handler `core/action_handlers.py`) — его тело не содержит `await`, поэтому мутации атомарны относительно event loop (гонки исключены, FR-011 соблюдён фактически, API не сломан).
> - T022: `_cleanup_expired() -> int` реализован как **async** (берёт lock) — в тестах вызывается через `await`.
> - T023: `dispatcher.start()` в `Container.build()` выполняется только при наличии running loop (в синхронных тестах пропускается — иначе `create_task` вне loop); `PlatformContext.shutdown()` — идемпотентная цепочка `adapter.stop() → fsm.shutdown() → dispatcher.stop()`, в `src/main.py` заменяет пару строк cleanup.
> - T024: `pytest tests/test_dispatcher_ttl.py tests/test_dispatcher.py` → **23 passed**; дополнительно `test_container.py` + `test_release_mechanism.py` → 49 passed суммарно.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T025 [P] Полный регресс: `.ai/scripts/run_checks.sh` (exit 0, покрытие ≥80%) + `pytest tests/ --ignore=tests/contract --ignore=tests/integration -q`, `pytest tests/contract -q`, `pytest tests/integration -q` — сравнить с baseline T003: ни одного нового падения (SC-007)
- [X] T026 [P] Пройти quickstart.md сценарии 1–6 полностью и обновить статусы в карте сценариев (при расхождениях — вернуться в соответствующую фазу)

> **Заметки Phase 6 (2026-09-29)**:
> - T025: `run_checks.sh` exit 0 (покрытие 92.9%); root+unit **78 failed / 1231 passed** (baseline 79/1207 — новых падений нет, −1 за счёт фикса `test_metrics`; структура падений идентична baseline: 51 device_service + 14 playwright + 5 cache + 3 models + 3 batcher + 2 discovery); `contract` 6 failed / 8 passed / 27 errors и `integration` 4 failed / 6 passed / 9 skipped — точь-в-точь baseline (SC-007 выполнен).
> - T026: все 6 сценариев пройдены, статусы внесены в «Карту сценариев → критерии» quickstart.md.
- [X] T027 [P] Обновить `.ai/01_PROJECT_STATE.md`: закрыть Known Issue #5 (тесты reconnect) и связанные пункты; дописать changelog; проверить Known Issues про Docker/healthcheck, если есть
- [X] T028 [P] Обновить `.ai/03_ROADMAP.md` Phase 9.8: пункты Docker Entrypoint / WebSocket Reconnect / Intent TTL отметить выполненными (с фактическими датами и ссылками на фиксы), обновить статус фазы; обновить `.ai/enhancements/20,21,22-*.md` (статус IMPLEMENTED + пометки о том, что 20/21 были частично выполнены до фичи 003); запустить `python3 .ai/scripts/sync_roadmap.py --auto-update`
- [X] T029 [P] Обновить статусы в самом спеке: `specs/003-critical-production-fixes/spec.md` → «Реализовано», checklist `checklists/requirements.md` — финальная сверка

---

## Dependencies & Execution Order

```
Phase 1 (T001-T002) ──┐
Phase 2 (T003) ───────┼──→ US1 (T004-T011)   [P1]
                      ├──→ US2 (T012-T016)   [P1, параллельно US1]
                      └──→ US3 (T017-T024)   [P2, параллельно US1/US2]
                                 │
                                 └──→ Phase 6 (T025-T029)
```

**Внутренние зависимости**:
- US1: T004→T006, T005→T007, T006+T007→T008→T009→(T010 опц.)→T011
- US2: T012→T013, T013→T014, T014→T015→T016
- US3: T017+T018→T019→T020→T021→T022→T023→T024
- Phase 6: T025 требует US1+US2+US3 завершёнными; T027-T029 — после T025

**US3 не зависит от US1/US2** (другие модули) — выполняется параллельно.

## Parallel Opportunities

- **US1 ∥ US2**: T004-T011 (cli/webui/docker) не пересекаются с T012-T016 (adapters/metrics)
- **T001 ∥ T002 ∥ T003** в Phase 1-2
- **T017 ∥ T018** (один файл `tests/test_dispatcher.py` и новый — да, разные файлы)
- **T004 ∥ T005** (разные тестовые файлы)
- **T027 ∥ T028 ∥ T029** в Phase 6 (разные файлы документации)
- **T014 ∥ T015**: частично (оба правят `ha_adapter.py`) → последовательно

## MVP Scope & Delivery

**MVP = US1 целиком (T001–T011)**: здоровый контейнер — критичнейший пункт (CRITICAL) и единственный, дающий value без изменений ядра.

**Инкрементальная доставка**:
1. **Инкремент 1 (MVP)**: US1 — контейнер поднимается, healthy, graceful stop. Можно коммитить и выкатывать независимо
2. **Инкремент 2**: US2 — тесты+метрика поверх уже работающего reconnect (параллелен инкременту 1)
3. **Инкремент 3**: US3 — TTL (самый объёмный, независим от 1-2)
4. **Финал**: Phase 6 — полный регресс + документация

## Implementation Strategy

1. **TDD строго**: тесты (T004, T005, T012, T017, T018) падают ДО реализации — зафиксировать падение
2. **Не верить enhancement вслепую**: 20/21 частично выполнены, 22 устарел в именах (`models.py` нет, `acquire()` = `submit()`) — правки только по фактическому коду
3. **Docker-фиксы только по факту**: T010 срабатывает лишь если T009 упал
4. **Не раздувать scope**: access control, DeviceSyncEvent, уникальность display_name — Known Issues 001, вне этой фичи
5. **Каждую историю коммитить отдельно** с прогоном `run_checks.sh`
