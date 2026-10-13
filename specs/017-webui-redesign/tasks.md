# Tasks: Веб-интерфейс инженера «Дом» (редизайн с нуля)

**Input**: Design documents from `/specs/017-webui-redesign/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (http-api.md, ws-events.md, ui-routes.md), quickstart.md

**Tests**: Включены — конституция проекта (принцип II, NON-NEGOTIABLE) требует TDD: тесты
пишутся до реализации. Для фронтенда используется зеркальная система (Vitest/RTL/MSW +
Playwright), для бэкенда — pytest.

**Organization**: Задачи сгруппированы по пользовательским историям; у каждой истории есть
собственная фаза, независимый тест и checkpoint.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: можно выполнять параллельно (разные файлы, нет незавершённых зависимостей)
- **[Story]**: к какой истории относится (US1…US6)
- В каждой задаче указан точный путь к файлу

## Path Conventions

- Фронтенд: `frontend/` (Next.js App Router, статическая сборка)
- Бэкенд: `src/webui/` (FastAPI, дополняется)
- Тесты бэкенда: `tests/unit/webui/`; E2E и юнит фронтенда: `frontend/tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Каркас фронтенд-проекта и инфраструктура сборки/качества

- [X] T001 Создать каркас Next.js (App Router, TypeScript) в `frontend/`: `frontend/package.json`, `frontend/tsconfig.json`, `frontend/next.config.ts` (с `output: 'export'`)
- [X] T002 [P] Настроить Tailwind и дизайн-токены в `frontend/tailwind.config.ts` и `frontend/src/styles/globals.css` (тёмная тема по умолчанию, локальные шрифты)
- [X] T003 [P] Подключить shadcn/ui локально (компоненты копируются, без CDN) в `frontend/src/components/ui/`
- [X] T004 [P] Настроить проверки качества фронтенда: `frontend/eslint.config.mjs`, `frontend/.prettierrc`, строгий `tsconfig.json` (`tsc --noEmit`)
- [X] T005 [P] Настроить Vitest + React Testing Library + MSW: `frontend/vitest.config.ts`, `frontend/tests/unit/setup.ts`
- [X] T006 [P] Настроить Playwright: `frontend/playwright.config.ts`, `frontend/tests/e2e/`
- [X] T007 Добавить цели Makefile `frontend-install`, `frontend-build`, `frontend-test`, `dev-frontend` в `Makefile`
- [X] T008 Добавить стадию сборки фронтенда в `deploy/docker/Dockerfile` (multi-stage: node → python, копирование `frontend/out`)
- [X] T009 [P] Добавить scoped pre-commit хуки для `frontend/` (eslint/tsc/prettier/vitest только для изменённых файлов) в `.pre-commit-config.yaml`
- [ ] T010 [P] Подготовить тестовый каркас бэкенда для новых маршрутов в `tests/unit/webui/conftest.py` (клиент с заголовками `X-User-ID`/`X-Is-Admin`)

**Checkpoint**: Сборка фронта и проверки работают; можно начинать фундамент

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Общая инфраструктура, без которой не работает ни одна история

**⚠️ CRITICAL**: Ни одна история не начинается до завершения этой фазы

- [X] T011 [P] Написать контрактный тест `GET /api/v1/session` в `tests/unit/webui/test_session_route.py` (идентичность, права, дефолт-отказ без заголовка)
- [X] T012 Написать тест раздачи статики и SPA-фолбэка в `tests/unit/webui/test_static_serving.py` (API-пути приоритетнее статики; неизвестный не-API путь отдаёт оболочку)
- [X] T013 [P] Реализовать `GET /api/v1/session` в `src/webui/routes/session.py` и зарегистрировать в `src/webui/app.py`
- [X] T014 Реализовать раздачу `frontend/out` (`StaticFiles(html=True)`) и SPA-фолбэк в `src/webui/app.py` (API/служебные маршруты регистрируются раньше)
- [X] T015 [P] Реализовать API-клиент с заголовками идентичности и разбором ошибок в `frontend/src/lib/api.ts`
- [X] T016 [P] Реализовать bootstrap идентичности в `frontend/src/lib/identity.ts` (читает `GET /api/v1/session`)
- [X] T017 [P] Настроить TanStack Query: провайдер и клиент в `frontend/src/lib/query-client.ts`, `frontend/app/providers.tsx`
- [X] T018 [P] Реализовать WS-клиент (`auth` → `subscribe` → реконнект с backoff) в `frontend/src/lib/ws.ts` по контракту `contracts/ws-events.md`
- [X] T019 Реализовать оболочку: `frontend/app/layout.tsx`, верхняя навигация по 5 разделам, тема — в `frontend/src/features/shell/`
- [X] T020 [P] Реализовать общие примитивы: бейджи состояния, индикаторы `stale`/`unavailable`, относительное время — в `frontend/src/components/`
- [X] T021 [P] Написать юнит-тесты клиентов и оболочки в `frontend/tests/unit/lib/` и `frontend/tests/unit/shell/`

**Checkpoint**: Фундамент готов — истории можно делать параллельно

---

## Phase 3: User Story 1 - Вижу состояние дома целиком (Priority: P1) 🎯 MVP

**Goal**: Первый экран показывает состояние каждой локации, устройства и тревоги; обновляется живьём.

**Independent Test**: Открыть `/`, назвать состояние дома без перехода в другие разделы; изменить датчик — увидеть обновление без перезагрузки; сделать датчик недоступным — увидеть это, а не пустое значение.

### Tests for User Story 1 ⚠️ (сначала тесты, до реализации)

- [X] T022 [P] [US1] Контрактный тест `GET /api/v1/overview` в `tests/unit/webui/test_overview_route.py`: формы ответа, фильтрация устройств по доступу, локации без фильтрации, `200` с пустыми списками vs `503` без движка, наличие тревог
- [X] T023 [P] [US1] Юнит-тесты отрисовки раздела «Дом» (значения с единицами, `stale`/`unavailable`, «данных нет») в `frontend/tests/unit/features/home/`
- [X] T024 [P] [US1] E2E US1 (состояние видно, живое обновление) в `frontend/tests/e2e/home.spec.ts`

### Implementation for User Story 1

- [X] T025 [US1] Реализовать вычисление тревог (`stale_sensor`, `unavailable`, `automation_mismatch`) в `src/webui/services/alerts.py`
- [X] T026 [US1] Реализовать агрегат `GET /api/v1/overview` в `src/webui/routes/overview.py` (локации со снимками + устройства + состояния автоматов + тревоги)
- [X] T027 [US1] Реализовать `WS /api/v1/ws/events` в `src/webui/routes/ws_events.py`: `state_change` по темам с проверкой прав при каждой доставке
- [X] T028 [US1] Реализовать страницу «Дом» в `frontend/app/page.tsx` и `frontend/src/features/home/` (локации, устройства, блок тревог)
- [X] T029 [US1] Реализовать страницу локации в `frontend/app/locations/[id]/page.tsx` (показания по ролям, производные, динамика)
- [X] T030 [US1] Подключить живые обновления к кэшу Query в `frontend/src/features/home/use-live.ts`
- [X] T031 [US1] Обработать пустые/ошибочные состояния (нет локаций, нет датчиков, `503`) в `frontend/src/features/home/states.tsx` — «данных нет» вместо выдумки (FR-029)

**Checkpoint**: US1 полностью работает и проверяется независимо (MVP-часть 1)

---

## Phase 4: User Story 2 - Управляю прибором быстро и с откликом (Priority: P1) 🎯 MVP

**Goal**: Управление светом/вентиляцией/шторами/климатом с мгновенным откликом и понятной ошибкой.

**Independent Test**: Нажать «выключить» — состояние отражается немедленно и подтверждается; на недоступном приборе — понятная причина; видно, учла ли команду автоматика.

### Tests for User Story 2 ⚠️

- [X] T032 [P] [US2] Контрактный тест команды устройства (`automation_synced`, ошибки `403`/`503`) в `tests/unit/webui/test_device_command.py`
- [X] T033 [P] [US2] Юнит-тест оптимистичной мутации и обработки ошибки в `frontend/tests/unit/features/devices/`
- [X] T034 [P] [US2] E2E управления (отклик, ошибка, признак автоматики, повторные нажатия) в `frontend/tests/e2e/control.spec.ts`

### Implementation for User Story 2

- [X] T035 [US2] Реализовать список устройств в `frontend/app/devices/page.tsx` (факт + автоматы + решения)
- [X] T036 [US2] Реализовать страницу устройства с управлением в `frontend/app/devices/[id]/page.tsx`
- [X] T037 [US2] Реализовать оптимистичную мутацию команды, паузу против дребезга и показ ошибки в `frontend/src/features/devices/use-command.ts`
- [X] T038 [US2] Показать признак «автоматика учла / команда ушла напрямую» в `frontend/src/features/devices/AutomationBadge.tsx`

**Checkpoint**: US1 + US2 работают независимо — это полный MVP («Дом + управление»)

---

## Phase 5: User Story 3 - Понимаю, почему так (Priority: P2)

**Goal**: На карточке/странице устройства — последнее решение с причиной и активная ручная блокировка со сроком.

**Independent Test**: Отключить свет при активном правиле — увидеть причину с относительным временем; включить блокировку — увидеть её и время окончания.

### Tests for User Story 3 ⚠️

- [X] T039 [P] [US3] Юнит-тесты отрисовки решения, причины и активной блокировки в `frontend/tests/unit/features/devices/reason.*`
- [X] T040 [P] [US3] E2E причины и блокировки в `frontend/tests/e2e/reason.spec.ts`

### Implementation for User Story 3

- [X] T041 [US3] Отдавать последнее решение и причину по устройству (в `src/webui/routes/devices/devices.py` или `overview.py`) на человеческом языке
- [X] T042 [US3] Реализовать блок «Почему так» (решение, причина, относительное время) в `frontend/src/features/devices/DecisionPanel.tsx`
- [X] T043 [US3] Реализовать активную ручную блокировку со сроком (используя `GET/DELETE /api/override`) в `frontend/src/features/devices/OverrideBadge.tsx`

**Checkpoint**: US1–US3 работают независимо

---

## Phase 6: User Story 4 - Разбираюсь в следствии (Priority: P2)

**Goal**: Живой журнал с фильтрами и трассировкой; диаграмма автомата с подсветкой текущего состояния.

**Independent Test**: Открыть журнал, отфильтровать по устройству и по trace, увидеть цепочку; открыть диаграмму — текущее состояние подсвечено и меняется живьём.

### Tests for User Story 4 ⚠️

- [X] T044 [P] [US4] Контрактный тест `GET /api/v1/events` (фильтры `device`/`location`/`level`/`trace`, курсор, пустой результат `200`) в `tests/unit/webui/test_events_route.py`
- [X] T045 [P] [US4] Юнит-тест виртуализации и фильтрации журнала в `frontend/tests/unit/features/journal/`
- [X] T046 [P] [US4] E2E журнала и диаграммы в `frontend/tests/e2e/journal.spec.ts`

### Implementation for User Story 4

- [X] T047 [US4] Реализовать `GET /api/v1/events` с фильтрами и курсорной пагинацией в `src/webui/routes/events.py`
- [X] T048 [US4] Реализовать страницу журнала (виртуальный живой хвост, фильтры) в `frontend/app/journal/page.tsx` и `frontend/src/features/journal/`
- [X] T049 [US4] Реализовать просмотр цепочки по `trace_id` (событие → решение → команда → результат) в `frontend/src/features/journal/TraceChain.tsx`
- [X] T050 [US4] Реализовать диаграмму автомата (`mermaid`) с подсветкой текущего состояния и живых переходов в `frontend/src/features/devices/FsmDiagram.tsx`

**Checkpoint**: US1–US4 работают независимо

---

## Phase 7: User Story 5 - Настраиваю дом (Priority: P3)

**Goal**: Подключение источников, импорт, устройства, поведения, локации, манифест; надёжные диалоги.

**Independent Test**: Подключить источник, импортировать устройство, задать поведение — устройство появляется на `/` без перезапуска; каждый диалог открывается и закрывается.

### Tests for User Story 5 ⚠️

- [X] T051 [P] [US5] Юнит-тесты валидации форм настроек (ошибки по полям) в `frontend/tests/unit/features/settings/`
- [X] T052 [P] [US5] E2E надёжности диалогов (регресс «модалки не открываются») в `frontend/tests/e2e/dialogs.spec.ts`

### Implementation for User Story 5

- [X] T053 [US5] Реализовать раздел «Настройка» (хаб) в `frontend/app/settings/page.tsx`
- [X] T054 [US5] Реализовать источники (список, подключение, импорт, синхронизация) в `frontend/app/settings/sources/` по существующим `…/devices/sources/*`
- [X] T055 [US5] Реализовать настройку устройств (конфигурация, поведения, доступ) в `frontend/app/settings/devices/`
- [X] T056 [US5] Реализовать настройку локаций и ролей датчиков в `frontend/app/settings/locations/`
- [X] T057 [US5] Реализовать редактор манифеста с ошибками по полям в `frontend/app/settings/manifest/`
- [X] T058 [US5] Ввести надёжный примитив диалога (Radix Dialog) в `frontend/src/components/ui/dialog.tsx` и использовать во всех формах

**Checkpoint**: US1–US5 работают независимо

---

## Phase 8: User Story 6 - Проверяю, здорова ли система (Priority: P3)

**Goal**: Готовность, источники, метрики и технические логи в одном разделе.

**Independent Test**: Отключить источник — увидеть это в `/system`; отличить «платформа не готова» от «в доме ничего не произошло».

### Tests for User Story 6 ⚠️

- [X] T059 [P] [US6] Юнит-тест отрисовки статуса системы (готовность, источники) в `frontend/tests/unit/features/system/`
- [X] T060 [P] [US6] E2E раздела «Система» в `frontend/tests/e2e/system.spec.ts`

### Implementation for User Story 6

- [X] T061 [US6] Реализовать страницу «Система» (`/ready`, `/health`, `/metrics`, технические логи) в `frontend/app/system/page.tsx` и `frontend/src/features/system/`

**Checkpoint**: Все истории функциональны независимо

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Замена старого UI, качество, документация, приёмка

- [X] T062 Удалить старый серверный UI: `src/webui/templates/`, HTML-страницы в `src/webui/routes/__init__.py` и `src/webui/routes_discovery.py`
- [X] T063 Удалить `tests/test_webui_playwright.py` и ссылки на него в конфигурации прогонов
- [X] T064 [P] Аудит отсутствия внешних запросов в `frontend/` и `src/webui/app.py`: убедиться, что нет обращений к CDN (FR-005, SC-005)
- [X] T065 [P] Проход по доступности и мобильной вёрстке (360 px) в `frontend/app/` и `frontend/src/components/` — SC-009
- [X] T066 [P] Проход по производительности (журнал 1000+ записей, первый экран) в `frontend/src/features/journal/` и `frontend/src/features/home/` — SC-004, SC-001
- [X] T067 [P] Обновить документацию: `README.md`, `docs/api/`, `.ai/01_PROJECT_STATE.md`, `.ai/02_ARCHITECTURE.md` (роль webui-слоя)
- [X] T068 Прогнать сценарии `specs/017-webui-redesign/quickstart.md` и зафиксировать результаты
- [X] T069 Живая приёмка на боевом доме (сценарии 1–6) и запись результата в `.ai/01_PROJECT_STATE.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: без зависимостей
- **Foundational (Phase 2)**: зависит от Setup — БЛОКИРУЕТ все истории
- **User Stories (Phase 3–8)**: зависят от Foundational; внутри — по приоритету (P1 → P2 → P3)
- **Polish (Phase 9)**: зависит от нужных историй

### User Story Dependencies

- **US1 (P1)**: после Foundational, ни от кого не зависит (MVP-часть 1)
- **US2 (P1)**: после Foundational; использует список устройств из US1, но тестируется независимо (MVP-часть 2)
- **US3 (P2)**: после Foundational; расширяет страницу устройства из US2
- **US4 (P2)**: после Foundational; независима
- **US5 (P3)**: после Foundational; использует примитив диалога (T058 — раньше форм)
- **US6 (P3)**: после Foundational; независима

### Within Each User Story

- Тесты пишутся и ПАДАЮТ до реализации
- Модели/данные → сервис/endpoint → UI
- Ядро истории до интеграции

### Parallel Opportunities

- Setup: T002–T006, T009, T010 — параллельно
- Foundational: T011, T013, T015–T018, T020, T021 — параллельно
- Внутри историй параллельны тестовые задачи (`[P]`), а также фронтенд и бэкенд (разные файлы)
- После фазы 2 истории US1…US6 могут делаться параллельно

---

## Parallel Example: User Story 1

```bash
# Тесты US1 (сначала, до реализации):
Task: "Контрактный тест GET /api/v1/overview в tests/unit/webui/test_overview_route.py"
Task: "Юнит-тесты раздела «Дом» в frontend/tests/unit/features/home/"
Task: "E2E US1 в frontend/tests/e2e/home.spec.ts"

# Реализация US1 (параллельно по разным файлам):
Task: "Вычисление тревог в src/webui/services/alerts.py"
Task: "WS /api/v1/ws/events в src/webui/routes/ws_events.py"
Task: "Страница «Дом» в frontend/app/page.tsx"
```

---

## Implementation Strategy

### MVP First (US1 + US2) 🎯

1. Phase 1: Setup
2. Phase 2: Foundational (блокирует всё)
3. Phase 3: US1 — «Дом»
4. Phase 4: US2 — управление
5. **STOP и VALIDATE**: проверить оба сценария независимо; при готовности — показать владельцу

MVP по решению владельца — «Дом + управление» (US1 + US2). Остальные истории добавляют
ценность инкрементально, не ломая предыдущие.

### Incremental Delivery

1. Setup + Foundational → фундамент
2. US1 → проверка → демонстрация
3. US2 → проверка → демонстрация (MVP закрыт)
4. US3 → US4 → US5 → US6 — по одной, каждая проверяется независимо
5. Polish: удаление старого UI и живая приёмка

---

## Notes

- `[P]` — разные файлы, нет зависимостей
- `[Story]` — трассировка к истории из spec.md
- Проверять, что тесты падают до реализации
- Коммит после каждой задачи или логической группы
- Не смешивать в одной задаче фронтенд и бэкенд одного и того же файла
