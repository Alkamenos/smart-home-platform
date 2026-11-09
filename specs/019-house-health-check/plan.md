# Implementation Plan: Health Check дома — единый список проблем

**Branch**: `019-house-health-check` | **Date**: 2026-11-09 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/019-house-health-check/spec.md`

## Summary

Health check уже существует в виде `HouseHealthService`: обход датчиков, молчание
по фиксированному порогу 6 часов, низкий заряд, недоступные сущности, сводка
проблем в `sensor.platforma_problemy_v_dome` и панель «Требует внимания» на
главной. Не хватает главного: **своего срока для каждого датчика**, молчания
батареек, обнаружения «команда принята, но не применена», истории и сохранения
проблем, persistent-уведомления в Home Assistant без спама и единого API.

План не переписывает обход, а расширяет его: ожидаемый интервал берётся из
`history.db` (медиана за 7 дней), порог — `max(2 × интервал, 2 часа)`; батарейки
проверяются раз в сутки (20 % и двое суток молчания); команды получают ожидание
применения на 5 минут; проблемы ведутся реестром с `first_seen`/`closed_at` и
переживают перезапуск; уведомление обновляется только при изменении состава и не
чаще раза в 24 часа.

## Technical Context

**Language/Version**: Python 3.12 (backend), TypeScript/Next.js (существующий frontend)

**Primary Dependencies**: FastAPI, Pydantic v2, asyncio, SQLite (`history.db`), loguru, pytest/pytest-asyncio, Vitest/Playwright. Новых зависимостей нет.

**Storage**: `history.db` (события датчиков — источник типичного интервала); `health_problems.json` и `health_notification.json` в `DATA_PATH` (атомарная запись, версия схемы); пороги — в манифесте `automation_rules.sensor_health`.

**Testing**: pytest + pytest-asyncio (unit/integration/contract), существующие frontend-тесты Vitest/Playwright.

**Target Platform**: Docker Linux (боевой контейнер), Windows для разработки.

**Project Type**: web-service + SPA; composition root в `src/app/`, ядро в `src/core/`, адаптеры в `src/adapters/`, веб-слой в `src/webui/` и `frontend/`.

**Performance Goals**: обход ~60–100 сущностей манифеста и батареек — не дольше 2 секунд; обнаружение изменения состава проблем — не дольше 5 минут; уведомление при неизменном составе — не чаще одного раза в 24 часа.

**Constraints**: обход не падает и не врёт при недоступном Home Assistant; HA при перезапуске отдаёт неполный список — «нет сущности» не объявляется сразу; ядро не импортирует адаптеры; автоматического ремонта нет.

**Scale/Scope**: 1604 сущности Home Assistant импортируются, но проблемы считаются только по сущностям манифеста и `battery_watch_entities` (~60–100); 27 автоматов; обход раз в 15 минут, батарейки — раз в сутки.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Принцип | Проверка | Итог |
|---|---|---|
| I. Event-Driven FSM | Структура `FSMDefinition`, debounce и таймеры не меняются; health check только читает состояния и решения | PASS |
| II. TDD/SDD | Спека и план до кода; тесты пишутся до реализации; покрытие новых файлов ≥80 % | PASS |
| III. Контроль у человека | Фича только наблюдает и сообщает; автоматического ремонта нет; повтор команд остаётся у сторожа | PASS |
| IV. Слои | `HouseHealthService` и реестр — в `core/`; уведомление — через протокол/адаптер, без импорта адаптеров из ядра | PASS |
| V. Манифест — источник конфигурации | Пороги, интервал обхода и список батареек — в `automation_rules.sensor_health`, значения по умолчанию в коде только как fallback | PASS |
| VI. Standalone/HA | Без Home Assistant обход и веб-список работают; уведомление и чтение состояний деградируют явно | PASS |
| VII. Интерфейсы | Веб-панель и persistent-уведомление HA используют один и тот же снимок проблем | PASS |

Нарушений нет. Complexity Tracking не заполняется.

## Project Structure

### Documentation (this feature)

```text
specs/019-house-health-check/
├── plan.md              # этот файл
├── research.md          # Phase 0: решения и альтернативы
├── data-model.md        # Phase 1: сущности и правила
├── quickstart.md        # Phase 1: сценарии живой проверки
├── contracts/
│   └── health-api.md    # Phase 1: контракт API и уведомления
├── checklists/
│   └── requirements.md  # качество спеки
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/core/models/health.py                 # HouseProblem, SensorExpectation, NotificationState
src/core/services/house_health.py         # обход: расширить, не переписывать
src/core/services/health_expectations.py  # ожидаемый интервал из history.db + роли
src/core/services/health_registry.py      # активные/закрытые проблемы, first_seen
src/core/services/health_notifier.py      # persistent-уведомление, антиспам
src/core/services/problems.py             # compose_report + новые виды проблем
src/core/commands/expectations.py         # CommandExpectationTracker (5 минут)
src/core/persistence/health_store.py      # атомарная запись health_problems.json
src/adapters/home_assistant/notifications.py  # persistent_notification.create/dismiss
src/app/house_services.py                 # проводка зависимостей
src/webui/routes/health.py                # /api/v1/problems, расширение /health
frontend/src/features/home/alerts-panel.tsx   # фильтры и причины
frontend/src/app/problems/page.tsx        # полный список проблем
frontend/src/lib/types.ts                 # типы Problem/ProblemLevel
tests/unit/services/test_health_*.py
tests/integration/test_health_*.py
tests/contract/test_health_api.py
```

**Structure Decision**: используется существующая слоистая структура. Новые
модули — в `core/services` и `core/models`; Home Assistant-уведомление — в
адаптере; веб-слой получает единый снимок через новый `/api/v1/problems`.
`HouseHealthService` сохраняет публичный интерфейс `sweep()`/`last_report` — его
уже читают `/api/v1/health`, overview и зеркало платформы.

## Что уже есть и чего не хватает

**Есть:**

- `HouseHealthService.sweep()`: датчики манифеста, недоступные, молчащие по
  общему порогу 6 часов, низкий заряд, отсутствующая сущность, «дом не
  прочитан»; реестр показаний по локациям и комнатам.
- `compose_report` + `watchdog_problems`: сводка обхода и сторожа в одном виде;
  `sensor.platforma_problemy_v_dome` через MQTT.
- `/api/v1/health`, `/api/v1/observation`; панель «Требует внимания» на главной
  (alerts из overview).
- Сторож: зависание, расхождение «автомат ↔ прибор», потеря HA.

**Не хватает (работа этой фичи):**

1. Свой ожидаемый интервал и порог молчания для каждого датчика (сейчас 6 часов
   для всех).
2. Молчание батареек (сейчас батарейки исключены из проверки молчания).
3. Обнаружение «команда принята, но не применена» (5 минут).
4. История проблем и сохранение `first_seen`/`closed_at` между перезапусками.
5. Persistent-уведомление HA с антиспамом (сейчас только датчик и панель).
6. Единый API проблем (`/api/v1/problems`) и полный список в интерфейсе.
7. Тесты на новые пороги, уведомления и команды.

## Phases

### Phase 0 — Research

`research.md` фиксирует решения:

- ожидаемый интервал — медиана интервалов событий из `history.db` за 7 дней;
- пороги по классам датчиков и отдельное правило для событийных датчиков;
- реестр проблем — JSON с атомарной записью, без новой таблицы SQLite;
- ожидание команды — трекер в диспетчере, читается обходом и сторожем;
- уведомление — `persistent_notification.create/dismiss` через адаптер, отпечаток
  состава + время последнего уведомления;
- веб-слой — расширить существующую панель и добавить страницу `/problems`.

### Phase 1 — Design & Contracts

- `data-model.md`: `HouseProblem`, `SensorExpectation`, `CommandExpectation`,
  `HealthCheckRun`, `NotificationState`; правила валидации и переходы
  `open → closed`.
- `contracts/health-api.md`: `GET /api/v1/problems`, расширение
  `GET /api/v1/health`, формат persistent-уведомления.
- `quickstart.md`: сценарии живой проверки — молчащий датчик, низкая батарейка,
  неприменённая команда, уведомление без спама, перезапуск.

### Phase 2 — Tasks (следующий шаг, `/speckit-tasks`)

Порядок работ:

1. Модели и реестр проблем с сохранением (P1, P5).
2. Ожидаемые интервалы и новые пороги молчания (P2).
3. Батарейки: 20 % и двое суток (P3).
4. Ожидание команды и `command_not_applied` (P4).
5. Уведомление HA с антиспамом (P5).
6. `/api/v1/problems` и страница `/problems` (P1).
7. Сквозные тесты и живая приёмка.

## Risks and Mitigations

| Риск | Как снижаем |
|---|---|
| Ложные «молчит» у событийных датчиков (движение, дверь) | отдельные правила: событийные не считаются молчащими без периодического heartbeat; порог по классу |
| HA перезапускается и отдаёт неполный список | «нет сущности» объявляется только после нескольких обходов подряд; при пустом ответе — «неизвестно» |
| Мало истории для расчёта интервала | fallback по типу датчика; первые 7 дней после установки — консервативный порог |
| Спам уведомлений | отпечаток состава + не чаще раза в 24 часа; при изменении — сразу, при решении — снятие |
| «Команда не применена» ложно срабатывает на переходах (штора едет, лампа плавно меняет яркость) | ожидание только для устойчивых состояний; допуск 5 минут; переходные состояния исключаются |
| Рост `health_problems.json` | хранить активные + закрытые за 30 дней, ограничение размера |

## Complexity Tracking

> Нарушений конституции нет; таблица не заполняется.
