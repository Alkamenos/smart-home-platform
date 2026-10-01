# 📋 BACKLOG — Единый пул задач

**Единственная точка входа для выбора следующей задачи.** Здесь собраны ВСЕ источники: Known Issues, Tech Debt из ROADMAP, бэклоги спецификаций, находки ревью кода, enhancement-расхождения. Не дублирует детали — только ссылки и разбивку на фичи/истории.

**Последнее обновление:** 2026-10-01

---

## Статус реализации F2 — завершено

**Baseline (T001):** `pytest tests/` = **1559 passed / 9 skipped / 0 failed**, покрытие 77%.
**Итог (T071):** **1725 passed / 9 skipped / 0 failed**, покрытие 93.4%, mypy --strict без ошибок, `run_checks.sh` exit 0. Все 71 задача выполнена (см. `specs/007-fsm-live-status/tasks.md`).

---

## Как работать с этим пулом

1. **Быстрые фиксы** (§1) — берутся как обычные задачи, без Spec Kit; после фикса — Known Issue в `01_PROJECT_STATE.md` закрывается.
2. **Крупные фичи** (§2) — перед стартом запускается Spec Kit: `speckit-specify` → спека `specs/NNN-<name>/` (следующий номер: **008**, 007 занята F2), далее clarify → plan → tasks → implement. После закрытия фичи — отметить статус здесь.
3. **Мелочи/бэклог** (§3) — без спеки, по мере сил.
4. **Отложено** (§4) — не планируется сейчас.
5. Обновлять этот файл после закрытия любой задачи из пула;ROADmap/PROJECT_STATE обновляются как обычно.

**Связанные файлы (не дублировать!):**
- `.ai/01_PROJECT_STATE.md` → Known Issues (детали багов)
- `.ai/03_ROADMAP.md` → фазы, Tech Debt (машиночитаемый)
- `.ai/enhancements/INDEX.md` → каталог предложений (⚠️ статусы 26/27/28 завышены — см. F1/F2)
- `specs/001-device-integration/tasks.md` → бэклог «EN/RU» задач

---

## §1. Быстрые независимые фиксы (без спеки)

| # | Задача | Источник | Приоритет | Статус |
|---|--------|----------|-----------|--------|
| Q1 | Починить loop-заражение `tests/test_webui_playwright.py` (живой event loop ломает ~51 async-тест в root-прогоне; после файла падает даже `asyncio.run`) — перевод тестов на sync playwright API или изоляция файла | Known Issue #13 | 🔴 High | ✅ 2026-09-30: sync-перевод + `--ignore` в addopts, root = 15/1301 (baseline) |
| Q2 | Убрать import file mismatch: совместный запуск `pytest tests/contract tests/integration` (нет `__init__.py` / `--import-mode=importlib`) | Known Issue #3 | 🔴 High | ✅ 2026-09-30: `--import-mode=importlib`, полный `pytest tests/` = 29/1354/9 (сумма baseline) |
| Q3 | Подключить `ConfigWatcher` к приложению (hot-reload манифеста; сейчас 0 инстанциаций) | Known Issue #8 | 🔴 High | ✅ 2026-09-30: под `HOT_RELOAD=1` (default OFF), +20 тестов, починены stop/детекция путей; риски до default-ON в Known Issue #8 |
| Q4 | Починить baseline-падения: root 15 + contract 6/27 + integration 4 (после Q1/Q2 картина улучшилась: полный прогон = 29 failed / 1374 passed) | Known Issue #4 | 🟡 Medium | ✅ 2026-09-30: все 29 устранены (6 багов в коде + 23 устаревших теста), полный прогон = 0 failed / 1411 passed / 9 skipped |
| Q5 | Проверить/починить enhancements-расхождения: 26 (фича 5 «WS в реальном времени» — все пункты `[ ]` при статусе ✅), 27/28 (мастер discovery/add-devices ✅, но нерабочие — см. F1) | INDEX.md | 🟡 Medium | ⬜ |
| Q6 | Починить отдельный прогон `tests/test_webui_playwright.py`: зависит на teardown playwright-сессии (`stop_sync`); устаревшие ассерты (`/health` → JSON, а тест ждёт "healthy") | Known Issue #13 (остаток) | 🟡 Medium | ✅ 2026-09-30: битая ASGI-цель (`src.webui.app:app`), `networkidle` при живом WS, CDN-гонка, JSON через `page.content()`, изоляция манифеста → 14 passed за 40с |
| Q7 | Добавить `MockAdapter.start()/stop()` (async no-op) — `run_platform` падает в mock-режиме без HA_TOKEN (локальный запуск невозможен) | Known Issue #14 | 🟡 Medium | ✅ 2026-09-30: no-op start/stop + 8 тестов, smoke `/health` ok |

---

## §2. Крупные фичи (через Spec Kit → `specs/NNN-*`)

### F1. Device Lifecycle: добавление устройства → FSM → работа ✅ (закрыто 2026-10-01)

**Была проблема:** единственный рабочий путь — ручной ввод в манифест через `/devices/save` (без FSM, оживёт после рестарта). Мастер `/discovery` нерабочий на 3 уровнях. Два несвязанных хранилища устройств. Enhancement 27/28 помечены ✅ фактически нерабочи.

**Спека при старте:** `specs/006-device-lifecycle/` (уточнить scope через clarify)

Истории:
- ✅ **US1 — Прямое добавление работает:** убрать дубль `@router.post("/apply")` (`src/webui/routes/devices/devices.py:99` vs `:585` — настоящий `apply_devices` недостижим); единое хранилище: `GET /api/v1/devices` должен отдавать устройства из `DeviceService`/persistence, а не in-memory `_devices_store` (`devices.py:27-28`); запись добавленного в persistence
- ✅ **US2 — Мастер discovery работает (закрыт 2026-10-01):** `discovery-data` отдаёт реальные устройства и области (причина недоступности — в теле ответа); идентичность (`X-User-ID`/`X-Is-Admin`) приходит из серверных атрибутов и подставляется во все запросы `/api/**`; форма создания источника с ошибками по полям и автовыбором; `discovery.html` переписан без дублей скриптов и htmx; мастер применяет через канонический `POST /api/v1/devices/apply`
- ✅ **US3 — Устройство оживает без рестарта:** FSM создаётся только в `Container.build()` — нужен hot-reload (`factory.create_and_register` / `_hot_reload_fsm`) или подключение ConfigWatcher (перекрывается с Q3); пробросить `ha_adapter` в webui `DeviceService` (`app.py:301` — сейчас `None`); перестройка маппинга EventRouter
- ✅ **US4 (опц.) — синк ↔ список:** после `POST /sources/{id}/sync` устройства появляются в `GET /api/v1/devices` (сейчас синк пишет в `DeviceService`, список читает другой мир)

**Итог:** все 4 истории закрыты, 47/47 задач. Подробности — в `.ai/01_PROJECT_STATE.md` и `specs/006-device-lifecycle/quickstart.md`.

### F2. Live FSM Statuses: статусы FSM в UI 🔴

**Была проблема:** статус «Active» на dashboard — хардкод (`dashboard.html:194`), `state` в REST — пустой dict, WebSocket-каналы мёртвые, `engine` ничего не публикует. WebUI живёт в отдельном мире: свой пустой `EventBus()` (`app.py:286`). Enhancement 26 заявлен ✅, но фича real-time не сделана.

**Спека при старте:** `specs/007-fsm-live-status/` ✅ **создана 2026-10-01** (4 US, 39 FR, 17 SC, 22 краевых случая, все 11 наблюдений подтверждены кодом; решения D-1/D-2 закодированы). ✅ **план готов 2026-10-01** (research/data-model/2 контракта/quickstart). ✅ **tasks.md готов 2026-10-01** — 71 задача, 7 фаз. Далее: `/speckit-implement`.

**Дополнительно найдено при сверке с кодом (сверх исходного описания):**
- Подписчик персистентности состояний FSM (`core/fsm/persistence.py:57`) подписан на `fsm.transition`, который никогда не публикуется → состояние автоматов **не сохраняется между перезапусками** (в HA-режиме атрибут `{entity}_mode`). Включено в объём фичи (решение D-1)
- `src/dashboard/dashboard.py:41` подписан на `fsm.state.changed` — тоже непубликуемое событие
- Подсветка состояния на диаграмме (`generate_with_highlight`) **вообще не существует** в проекте (заявлена в enhancement 26)
- Диаграмма отдаётся как JSON (`webui/routes/__init__.py:155`), а вставляется в страницу как текст (`dashboard.html:242`)
- `/api/ai/suggestions` — третий раздел с mock-данными помимо heatmap и истории событий

**Найдено при исследовании кода для плана (2026-10-01) — 3 дефекта включены в фичу как блокирующие:**
- `FSMEngine` создаётся **без диспетчера** (`container.py:130`) → `CommandIntent` отбрасываются (`engine.py:324-328`): автоматика меняет состояние FSM, но **не отправляет команды устройствам**
- `FSMEngine` создаётся **без хранилища** → `save_state`/`load_state` мертвы, состояние никогда не восстанавливается
- `FSMPersistence` вызывает несуществующий `adapter.set_entity_state` (`fsm/persistence.py:180`) — метода нет ни у одного адаптера

**Исследование плана (`research.md`, 11 решений):** R-01 инъекция зависимостей движка; R-02 публикация в двух точках (успех/отказ, 5 причин); R-03 источник перехода по префиксу `manual_*` (в движке признака источника нет вообще); R-04 `State.entered_at` — монотонные часы цикла, публикуется настенное ISO-8601; R-05 `publish` блокирует и не поддерживает sync-подписчиков (каждый вызов логирует ложную ошибку); R-06 источник истины — `StatePersistence`, зеркало в HA через существующий диспетчер; R-07 одна шина на процесс; R-08 база — существующий канал `/api/v1/ws/devices`, `/ws/live` мёртв и без проверки прав; R-09 диаграмма — чистая Mermaid-строка, подсветка на клиенте; R-10 графики строятся на `EventStore` (таблицы `fsm_transitions`/`events` существуют, **писателей нет ни одного**), ось времени графика была перепутана; R-11 заморожено: правила переходов, реестр гвардов, middleware, метрики.

Истории:
- **US1 — Источник событий:** публикация переходов FSM в шину (`engine.py` логирует, но не публикует `fsm.transition`/`fsm.state.changed`); мост WebUI ↔ Container: один EventBus вместо пустого нового (`app.py:286`); подписка `DeviceService.handle_state_change` (`device_service.py:719` — нигде не подписан)
- **US2 — REST-состояния:** эндпоинт `GET /api/fsm/state` поверх `FSMEngine.get_all_states()` (`engine.py:219`, заявлен в enhancement 26:115); поля `state` в `GET /api/v1/devices` из реального состояния (сейчас — `_devices_store`)
- **US3 — Live в UI:** вызывать `broadcast_state_change()` (`websocket.py:368` — вызывается только в тестах) → подключить UI к сокету (сейчас только `/ws/live` с пустым JS-хендлером `index.html:844`); фикс рендера диаграмм на dashboard (JSON вставляется как HTML: `dashboard.html:242` vs `routes/__init__.py:155`); подсветка текущего состояния в Mermaid (`generate_with_highlight` не реализован)
- **US4 (опц.) — честные данные:** heatmap `random.seed(42)` (`routes/__init__.py:215`), график 24ч читает таблицу без writer'ов (`routes/__init__.py:261`) — починить или удалить

### F3. Observability FSM: метрики, watchdog, dashboard-интеграция 🟡

**Проблема:** метрики FSM — no-op (`MetricsCollector.initialize()` не вызывается, `record_fsm_transition` нигде не вызывается, `/metrics` не подключён к FastAPI); watchdog не инстанцируется + баг (`state_obj.current` вместо `current_state`, `watchdog.py`); `DashboardIntegration` подписан на непубликуемое `fsm.state.changed`.

**Спека при старте:** `specs/008-fsm-observability/` (можно объединить с F2, если clarify покажет общность)

Истории:
- **US1:** подключить `/metrics` в FastAPI + вызов `initialize()` + реальные записи переходов FSM
- **US2:** подключить WatchdogService (или удалить), починить баг `current_state`, снимки состояний в лог/metrics
- **US3:** связать `DashboardIntegration` с реальной шиной (перекрывается с F2 US1)

### F4. E2E и интеграционные тесты device-integration 🟡

**Проблема:** 0 из 6 E2E (Tech Debt Medium #0); CLI — без интеграционных тестов (Medium #4).

**Спека при старте:** `specs/009-device-e2e/`

Истории:
- **US1:** E2E sync/config/commands/access (EN T040, T046, T054, T060, T067 — `test_device_*_e2e.py`)
- **US2:** интеграционные тесты CLI (`shp bulk-import`, health)
- **US3:** `tests/unit/adapters/`, `tests/unit/core/test_encryption.py` (EN T005, T011)

---

## §3. Мелочи и бэклог (без спеки)

| # | Задача | Источник | Статус |
|---|--------|----------|--------|
| B1 | RU T035 — валидация уникальности `display_name` (CHK012) | specs/001 | ⬜ |
| B2 | RU T081 — финальная проверка логирования всех операций (ТР-010: sync/delete ещё не пишутся) | specs/001 | ⬜ |
| B3 | EN T047 — `DeviceSyncService`; EN T022/T023 — persistence для команд устройств | specs/001 | ⬜ |
| B4 | `.env.example` + документация `ENCRYPTION_KEY` (EN T009/T075) | specs/001 | ⬜ |
| B5 | Known Issue #9 — мёртвый канал `params.motion_sensor` (устранить или удалить) | PROJECT_STATE | ⬜ |
| B6 | Known Issue #10 — MockAdapter не маршрутизирует state change | PROJECT_STATE | ⬜ |
| B7 | Known Issue #12 — `Task was destroyed` при остановке контейнера | PROJECT_STATE | ⬜ |
| B8 | Dashboard Generator: CLI `shp generate-dashboard` (enhancement 19, Phase 9.75 остаток) | ROADMAP 9.75 | ⬜ |
| B9 | Tech Debt Low #5 — dashboard generator → Jinja2 | ROADMAP | ⬜ |
| B10 | Удалить/починить автофикстуру `tests/conftest.py::webui_server` — битая ASGI-цель `src.webui.app:app`, ~15с ожидания и мёртвый процесс на каждый прогон; тесты её не используют | Known Issue #13 (остаток Q6) | ⬜ |

---

## §4. Отложено (не планируется)

- Phase 11: LLM/NLP адаптер (enh 10), Event History Data Lake (enh 23), Predictive AI Middleware (enh 24), hot-reloading guard/action-функций (enh 14)
- Phase 12: plugin system, multi-instance, voice assistants, ML
- Cancelled: GraphQL, multi-tenant, visual FSM editor (не реанимировать)

---

## Статусы фич

| Фича | Спека | Статус |
|------|-------|--------|
| F1 Device Lifecycle | specs/006 | ✅ **Выполнено 2026-10-01** — 47/47 задач. US1: единый источник устройств + транзакция жизненного цикла, форма `/devices/save` с обязательным источником; US2: мастер на реальных данных источника, `ManifestStore` в core, идентичность в запросах UI, `discovery.html` без дублей; US3: синк сводится с единым хранилищем (без дублей), `removed_from_ha` снимает автоматику, сбой не теряет данные; US4: каскадное удаление + `DELETE /api/v1/devices/{id}` + действие в UI. **Проверено:** 1559 passed / 9 skipped / 0 failed, mypy --strict ✅, run_checks exit 0, quickstart 1–6 и 9 вживую (Traceback 0); покрытие: `device_lifecycle` 93%, `manifest_store` 96%, `discovery_service` 91%, `routes_discovery` 95%, `event_router` 95% | spec (4 US, 30 FR, 10 SC), research, plan, data-model, 2 контракта, quickstart (9 сценариев + фактические результаты), tasks.md (47) |
| F2 Live FSM Statuses | specs/007 | ✅ **Выполнено 2026-10-01** — 71/71 задач. US1: переходы публикуются и доходят до подписчиков, состояния переживают перезапуск, команды доходят до диспетчера; US2: `GET /api/fsm/state` + `fsm`/`automation` в устройстве с разграничением прав; US3: живой канал устройств вместо мёртвого `/ws/live`, диаграмма как схема, подсветка состояния; US4: графики по фактическим данным, выдумка удалена. **Проверено:** 1725 passed / 9 skipped / 0 failed, Playwright 23 passed (2 предсуществующих падения — Known Issue #15), mypy --strict 0 ошибок, run_checks exit 0, покрытие 93.4%. Попутно устранены 7 дефектов вне буквального объёма (диспетчер/хранилище движка, двойная загрузка модулей, неразбираемый Mermaid, скрытый контейнер отрисовки, утечка прав, перепутанная ось времени, 500 на ответе подсказки) | spec (4 US, 39 FR, 17 SC), research (11 решений), plan (6 волн), data-model (7 сущностей), contracts (2), quickstart (11 сценариев + фактические результаты), tasks.md (71, все выполнены) | Переходы публикуются, состояния переживают перезапуск, команды доходят до диспетчера US1: публикация переходов FSM в шину + единая шина для WebUI + подписка `handle_state_change` + восстановление состояний при перезапуске; US2: `GET /api/fsm/state` + реальный `state` в списке устройств; US3: живые обновления с правами доступа, переподключение, починенный рендер диаграмм, подсветка текущего состояния; US4: запись переходов и событий в `EventStore`, удаление mock-данных → «данных нет». **План:** 6 волн (фундамент → US1 → US2 → US3 → US4 → полировка), Constitution Check PASS, 11 решений в research, 6 рисков с mitigation. **Tasks:** 71 задача, 7 фаз (Setup 3, Foundational 11, US1 14, US2 8, US3 14, US4 10, Polish 11), 34 параллельные; Foundational блокирует всё; US3 и US4 параллельны после US1 | spec (4 US, 39 FR, 17 SC, 22 edge cases), research (11 решений), plan (6 волн, 6 рисков), data-model (7 сущностей), contracts (события + REST/WS), quickstart (11 сценариев, 9 без HA), tasks.md (71) |
| F3 FSM Observability | specs/008 (будет) | ⬜ Не начата |
| F4 Device E2E | specs/009 (будет) | ⬜ Не начата |
| ~~US4 Access Control~~ | specs/004 | ✅ Закрыта 2026-09-30 |
| ~~Device Audit Log~~ | specs/005 | ✅ Закрыта 2026-09-30 |
