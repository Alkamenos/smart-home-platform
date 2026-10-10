# Модель данных: климат и вентиляция (спека 014)

**Дата**: 2026-10-10. Источник истины по значениям — Home Assistant, проверено
REST 2026-10-10.

Все значения по умолчанию обоснованы в `research.md` (D12).

---

## 1. Доменные правила климата

Расширение `AutomationDomainRules` (`src/core/models/manifest.py:71-118`).
Сейчас климатический домен не имеет ни одного поля — правила из
`automation_rules.climate` невозможно задать.

| Поле | Тип | Сущность по умолчанию | Назначение |
|------|-----|------------------------|------------|
| `setpoint_entity` | `str \| None` | `input_number.temperatura` | Цель обогрева |
| `comfort_max_entity` | `str \| None` | `input_number.maksimalno_komfortnaia_temperatura` | Потолок комфорта |
| `season_entity` | `str \| None` | `input_boolean.zima` | Сезон: кондиционер зимой запрещён |
| `feature_entity` | `str \| None` | `input_boolean.feature_climate` | Фиче-флаг: выключен — только наблюдение |
| `ac_gate_entity` | `str \| None` | `input_boolean.ispolzovat_konditsioner` | Разрешение владельца на кондиционер |
| `setpoint_min` | `float \| None` | 5.0 | Нижняя граница допустимой уставки |
| `setpoint_max` | `float \| None` | 30.0 | Верхняя граница допустимой уставки |

**Правила валидации** (FR-044):

- `setpoint_min < setpoint_max`, иначе ошибка загрузки манифеста.
- Уставка вне `[setpoint_min, setpoint_max]` → отказ с причиной
  `setpoint_unavailable`, а не подстановка запасного значения.
- Пустая строка в `*_entity` → ошибка загрузки, а не «молча не работает».
  Основание: пустая сущность в манифесте даёт пустой список подписки, и
  отказ выглядит как штатное поведение.

---

## 2. Доменные правила вентиляции

Расширение того же класса (`automation_rules.ventilation`). Сущности проверены в
доме и отвечают.

| Поле | Тип | Сущность по умолчанию | Ключ контекста |
|------|-----|------------------------|----------------|
| `feature_entity` | `str \| None` | `input_boolean.feature_ventilation` | `ventilation_enabled` |
| `enable_entity` | `str \| None` | `input_boolean.ventiliatsiia` | `ventilation_on` |
| `airing_entity` | `str \| None` | `input_boolean.provetrivanie` | `airing_on` |
| `exhaust_entity` | `str \| None` | `input_boolean.provetrivanie_vytyazhka` | `exhaust_on` |
| `outside_temp_entity` | `str \| None` | `sensor.temperatura_na_ulitse_srednee` | `outside_temperature` |
| `manual_lockout_min` | `int \| None` | 15 | Срок уважения ручного вмешательства |

**Правила валидации**: `manual_lockout_min ≥ 0`; пустые строки — ошибка
загрузки.

### Исключение мёртвых сущностей (FR-036)

В доме отвечают `unavailable` и на них вешать автоматику бессмысленно:
`climate.kitchen_ac`, `climate.beok_tr9b_thermostat`, `climate.beok_tr9b_thermostat_2`.

Правило: **недоступная сущность исключается из манифеста, а не приводит к
отказу при загрузке**. Проверка — `unavailable` при синхронизации, не «мёртвая
по имени».

Причина неочевидна: в прошлый раз похожая правка молча посадила двадцать
чужих светильников в неверную комнату (Known Issue #88). Здесь то же самое
выглядело бы как «вентиляция работает, но выключается» — и искать пришлось бы
не там.

---

## 3. Ключи контекста перехода

Словарь, который читают условия и действия. Существующие ключи не меняются,
добавляются новые.

### Считываются адаптером (значения из Home Assistant)

| Ключ | Тип | Источник | Состояние |
|------|-----|----------|-----------|
| `daylight` | `bool` | `sun.sun` | есть, `ha_adapter.py:1482` |
| `sleep_modifier_on` | `bool \| None` | `sleep_modifier` | есть, `ha_adapter.py:1486` |
| `climate_setpoint` | `float \| None` | `setpoint_entity` | **новое** |
| `comfort_max` | `float \| None` | `comfort_max_entity` | **новое** |
| `is_winter` | `bool \| None` | `season_entity` | **новое** |
| `climate_enabled` | `bool \| None` | `feature_entity` | **новое** |
| `ac_allowed` | `bool \| None` | `ac_gate_entity` | **новое** |
| `ventilation_enabled` | `bool \| None` | `ventilation_entity` | **новое** |
| `ventilation_on` | `bool \| None` | `ventilation.enable_entity` | **новое** |
| `airing_on` | `bool \| None` | `ventilation.airing_entity` | **новое** |
| `exhaust_on` | `bool \| None` | `ventilation.exhaust_entity` | **новое** |
| `outside_temperature` | `float \| None` | `ventilation.outside_temp_entity` | **новое** |

### Считываются роутером (измерение датчика)

| Ключ | Тип | Роль |
|------|-----|-------|
| `temperature` | `float \| str` | `temperature` |
| `humidity` | `float \| str` | `humidity` |

`event_router.py:205-207` кладёт измерение **под именем роли**.

### Считываются движком из параметров поведения

| Ключ | Источник |
|------|----------|
| `hysteresis` | `behavior.params` |
| `managed_by_hardware` | `behavior.params` |
| `heater_timer` | `behavior.params` |
| `run_minutes` | `behavior.params` |
| `room`, `target_device_id` | `FSMDefinition` |
| `percentage`, `preset_mode` | `behavior.params` вентиляции |

**Правило нечитаемости** (FR-037): `unavailable`, `unknown`, пустая строка и
нечисловая строка равны отсутствию данных. Проверяется `_is_measurement`
(`engine.py:89-113`) при объявлении `requires` и `_temperature_value`
(`builtin.py:646`) при чтении условием.

---

## 4. Параметры поведения `climate_control`

Объявляются в `src/features/CONTRACT.yaml`, иначе веб-интерфейс отвергнет
параметр (`core/behavior_params.py:88-94`).

| Параметр | Тип | Диапазон | По умолчанию | FR |
|----------|-----|----------|--------------|-----|
| `heater_timer` | `str` | entity_id | нет | FR-004 |
| `run_minutes` | `float` | 1–43200 | 15 | FR-005 |
| `hysteresis` | `float` | 0–5 | 0.5 | FR-006 |
| `managed_by_hardware` | `bool` | — | false | FR-008 |

`timeout_sec` перехода задаётся в YAML явно (`research.md` D4), а не
через `run_minutes`: разные вещи. `run_minutes` — сколько работает обогреватель
в HA; `timeout_sec` — через сколько автомат принимает решение заново.

---

## 5. Параметры поведения `ventilation_modes`

| Параметр | Тип | Диапазон | По умолчанию | FR |
|----------|-----|----------|--------------|-----|
| `mode_supply` | `str` | из списка устройства | `Приток` | FR-019 |
| `mode_summer` | `str` | из списка устройства | `Рекуперация (лето)` | FR-019 |
| `mode_winter` | `str` | из списка устройства | `Рекуперация (зима)` | FR-019 |
| `mode_night` | `str` | из списка устройства | `Ночной` | FR-019 |
| `mode_airing` | `str` | из списка устройства | `Приток MAX` | FR-024 |
| `mode_exhaust` | `str` | из списка устройства | `Вытяжка` | FR-026 |
| `speed_normal` | `int` | 0–100 | 30 | FR-020 |
| `speed_delta_gain` | `float` | 0–20 | 5.0 | FR-020 |
| `speed_night_max` | `int` | 0–100 | 20 | FR-022 |
| `delta_deadband` | `float` | 0–2 | 0.3 | FR-030 |
| `airing_seconds` | `float` | 60–86400 | 3600 | FR-025 |
| `source_room` | `str` | id комнаты | самая тёплая | FR-001 вентиляции |

**Почему режимы — параметры, а не константы кода** (`research.md` D7): список
режимов принадлежит устройству. Зашитый в код режим означал бы, что замена
рекуператора на другой с сохранением набора режимов потребует правки кода.

**Скорость по разнице температур** (FR-020): считается как
`speed_normal + |улица − комната| × speed_delta_gain`, с нулём в мёртвой зоне
`|Δ| ≤ delta_deadband` (FR-030), ограничением 0–100 и ночным потолком
(FR-022, только понижение).

---

## 6. Состояния автоматов

### `climate_control` (изменение)

Добавляется ради FR-018: охлаждение в комнате, где нет кондиционера, —
законное решение, а не отказ.

| Состояние | Значение |
|-----------|----------|
| `IDLE` | Обогревать нечего |
| `HEATING` | Обогреватель работает по своему таймеру |
| `COOLING` | Кондиционер охлаждает |
| `DRYING` | Кондиционер осушает |

Переход в `COOLING` требует гейта `ac_allowed` и `not is_winter` — иначе
остаётся `IDLE` с записью причины (FR-014).

### `DRYING` — почему отдельное состояние (FR-017)

Осушение и охлаждение — разные режимы кондиционера, и режим у него общий:
`set_hvac_mode` переключает `cool` в `dry`. Значит, это **одно** решение на
комнату, а не два: если бы осушение было отдельным автоматом, а охлаждение
другим, они бы драться за один `hvac_mode` — и владелец получил бы сообщение
об аварии при каждом переключении порога.

Переход в `DRYING` разрешён только вне зимы (FR-011 наоборот: охлаждение
запрещено зимой, осушение в доме зимой бессмысленно — воздух и так сухой).

**Правило выбора**: если комната выше потолка комфорта — охлаждение
приоритетнее осушения. Одна комната не может иметь два активных режима.

### `ventilation_modes` (новый)

| Состояние | Значение |
|-----------|----------|
| `IDLE` | Рекуператоры выключены |
| `SUPPLY` | Обычный режим по погоде |
| `AIRING` | Проветривание, самоотключение по таймеру |
| `EXHAUST` | Режим вытяжки |

`EXHAUST` — отдельное состояние, а не флаг: вытяжка меняет не скорость
притока, а направление. Совмещение в одном автомате с притоком дало бы
автомат, который держит два разных намерения одновременно.

---

## 7. Причины отказов

Словарь причин ограничен (`src/core/events/fsm_events.py:108-121`), имена
должны совпадать с константами — иначе откат в `guard_failed` и потеря смысла
в журнале.

| Причина | Когда | Уже есть |
|---------|-------|----------|
| `climate_disabled` | `feature_climate` = off | ✅ `fsm_events.py` |
| `managed_by_hardware` | в комнате штатный термостат | ✅ |
| `setpoint_unavailable` | уставка отсутствует или вне диапазона | ✅ |
| `guard_data_missing` | нет показания или уставки | ✅ |
| `not_cold_enough` | комната не холоднее цели | ✅ |
| `ac_forbidden_in_winter` | `zima` = on | ✅ константа есть, guard нет |
| `ac_not_allowed` | гейт кондиционера выключен | **новая** |
| `above_comfort_ceiling` | охлаждение не требуется | **новая** |
| `ventilation_disabled` | `feature_ventilation` = off | **новая** |
| `turned_off_by_owner` | `ventiliatsiia` = off | **новая** |
| `outside_temp_missing` | улица недоступна | **новая** |
| `sensor_stale` | датчик не отвечает дольше срока | **новая** |

Последние шесть добавляются вместе с условиями, которые их называют.

---

## 8. Наблюдаемость

| Что | Где | Требование |
|-----|-----|-----------|
| Причина каждого решения | журнал | FR-010, FR-032 |
| Момент отказа датчика и возврата | журнал | FR-045 |
| Заряд батареи ниже порога | журнал, предупреждение | FR-033, FR-048 |
| Длительность работы обогревателя | состояние автомата + `expected_timeout_sec` | FR-004 |
| Текущий режим и скорость рекуператора | состояние автомата + решение | FR-003 |

Порог низкого заряда — 20 %: ниже батарейку уже пора менять, выше — успеет сесть в
дороге (`research.md` D12).
