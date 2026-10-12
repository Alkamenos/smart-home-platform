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

Параметры уточнены по решению владельца (`research.md` D18) и приведены в
соответствие с кодом при переработке шаблона (T059, T085–T090). Один шаблон
обслуживает и рекуператор, и вытяжку: род устройства задаёт `ventilation_role`.

| Параметр | Тип | Диапазон | По умолчанию | FR |
|----------|-----|----------|--------------|-----|
| `ventilation_role` | `str` | `supply` \| `exhaust` | `supply` | FR-028 |
| `mode_summer` | `str` | из списка устройства | `Рекуперация (лето)` | FR-019, FR-050 |
| `mode_winter` | `str` | из списка устройства | `Рекуперация (зима)` | FR-019, FR-050 |
| `mode_airing` | `str` | из списка устройства | `Приток MAX` | FR-024, FR-051 |
| `winter_mode_threshold` | `float` | 0–30 | 5.0 | FR-019 |
| `speed_normal` | `int` | 0–100 | 42 | FR-020, FR-052 |
| `speed_min` | `int` | 0–100 | 14 | FR-022, FR-052, FR-053 |
| `speed_cold_reference` | `float` | −30–30 | 5.0 | FR-052 |
| `speed_cold_gain` | `float` | 0–20 | 2.0 | FR-052 |
| `airing_seconds` | `float` | 60–86400 | 3600 | FR-025, FR-051 |
| `exhaust_seconds` | `float` | 60–86400 | 3600 | FR-025 |
| `exhaust_temp_threshold` | `float` | 0–50 | 25.0 | FR-026 |
| `exhaust_humidity_threshold` | `float` | 0–100 | 65.0 | FR-026 |

`mode_night` и `mode_exhaust` из первой редакции удалены: ночью задаётся скорость
(`speed_min`), а не режим, а вытяжка — отдельный прибор без режимов. По тому же
правилу (`research.md` D22) удалены ставшие инертными `mode_supply`,
`supply_delta_threshold`, `speed_delta_gain`, `speed_night_max`, `delta_deadband`:
приток по дельте отменён, а ночной потолок заменён минимумом. Параметр без силы
форма поведения показывать не должна.

**Почему режимы — параметры, а не константы кода** (`research.md` D7): список
режимов принадлежит устройству. Зашитый в код режим означал бы, что замена
рекуператора на другой с сохранением набора режимов потребует правки кода.

**Выбор режима** (`research.md` D22, FR-050/FR-051): жарко (температура комнаты
выше `comfort_max` = `input_number.maksimalno_komfortnaia_temperatura`) →
`mode_airing` («Приток MAX») на `airing_seconds`, затем возврат к обычному режиму.
Иначе режим задаёт модификатор сезона: `is_winter` = true → `mode_winter`, false →
`mode_summer`; пока сезон не прочитан — `winter_mode_threshold` относительно
температуры улицы. Режима «Приток» по дельте больше нет: он остужал дом (D20).

**Немедленное действие переключателей** (T093, FR-054): выключатель владельца,
фиче-флаг дома, сезон и модификаторы проветривания/вытяжки меняются в Home
Assistant, а не от датчика. Их смена доносится автоматам вентиляции событием
`settings_changed` (`EventRouter.route_settings_change`), а не ожиданием
следующего `temperature_changed`: без этого решение владельца не действовало,
пока молчал датчик комнаты.

**Скорость** (FR-020, FR-052, FR-053): обычная скорость `speed_normal`; при
понижении температуры улицы ниже `speed_cold_reference` скорость уменьшается на
`speed_cold_gain` процентов за градус, но не ниже `speed_min`. Ночью (модификатор
«мы спим») при нормальной температуре комнаты скорость равна `speed_min`. Комнатная
температура приходит в контекст под именем роли датчика (`temperature`), а не
отдельного параметра `source_room`: прежний ключ `source_room_temperature` никто
не писал, и скорость отказывала «датчик не даёт показания» при живом датчике.

**Вытяжка** (FR-026, T086): включается модификатором владельца ИЛИ по
температуре и/или влажности санузла; гасится, когда снят модификатор и санузел
вернулся в норму.

**Автосброс модификаторов** (T085): проветривание и вытяжка держатся не больше
`airing_seconds` / `exhaust_seconds`, затем платформа возвращает обычный режим и
записывает `input_boolean` модификатора в `off` (действия
`airing_after_timeout` / `exhaust_after_timeout`).

**Право работать (стоять/дышать)** (FR-027, FR-031, FR-049, FR-055): вентиляция
рекуператоров выключается, когда `ventilation_on` = off (выключатель владельца),
`ventilation_enabled` = off (фиче-флаг дома) **или температура комнаты ниже
уставки** `climate_setpoint` (`input_number.temperatura`) — причина
`room_below_setpoint`. Прибор выключается, а не крутится на нуле. Отдельного
правила по работающему обогреву больше нет: пока комнате нужен обогрев, она ниже
уставки, и вентиляция стоит сама (D22).


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
| `IDLE` | Прибор стоит: выключен владельцем, идёт обогрев или данных нет |
| `SUPPLY` | Обычный режим: режим по модификатору «зима» и дельте, скорость по разнице |
| `AIRING` | Проветривание по модификатору, самоотключение по таймеру |
| `EXHAUST` | Вытяжка санузла: по модификатору либо по температуре/влажности |

`EXHAUST` — отдельное состояние, а не флаг: вытяжка меняет не скорость
притока, а направление. Совмещение в одном автомате с притоком дало бы
автомат, который держит два разных намерения одновременно.

Переходы (все на событии датчика `temperature_changed`, для санузла ещё и
`humidity_changed`; `timeout` — из движка):

| Из | В | Условие | Действие |
|----|----|---------|----------|
| IDLE | AIRING | `owner_wants_airing` | `fan_set_preset` |
| IDLE | EXHAUST | `should_run_exhaust` | `exhaust_on` |
| IDLE | SUPPLY | `mode_for_weather` | `fan_apply_mode_and_speed` |
| SUPPLY | AIRING | `owner_wants_airing` | `fan_set_preset` |
| SUPPLY | SUPPLY | `speed_within_limits` | `fan_set_percentage` |
| SUPPLY | IDLE | `ventilation_should_stop` | `fan_turn_off` |
| AIRING | SUPPLY | `timeout` | `airing_after_timeout` |
| AIRING | IDLE | `ventilation_should_stop` | `fan_turn_off` |
| EXHAUST | IDLE | `timeout` | `exhaust_after_timeout` |
| EXHAUST | IDLE | `exhaust_should_stop` | `exhaust_off` |

Роль устройства (`ventilation_role`) отделяет рекуператор от вытяжки: условия
`owner_wants_airing`/`mode_for_weather`/`speed_within_limits`/
`ventilation_should_stop` работают только для `supply`, а `should_run_exhaust`/
`exhaust_should_stop` — только для `exhaust`.

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
| `ac_forbidden_in_winter` | `zima` = on | ✅ |
| `ac_not_allowed` | гейт кондиционера выключен | ✅ |
| `not_above_comfort` | охлаждение не требуется | ✅ |
| `ventilation_disabled` | `feature_ventilation` = off | ✅ |
| `turned_off_by_owner` | `ventiliatsiia` = off | ✅ |
| `outside_temp_missing` | улица недоступна | ✅ |
| `sensor_stale` | датчик не отвечает дольше срока | ✅ |
| `room_below_setpoint` | температура комнаты ниже уставки — вентиляция не нужна | ⏳ (T095, FR-049) |
| `heating_active` | в комнате работает обогрев | ⊘ заменено правилом по уставке (D22, FR-055) |
| `bathroom_comfortable` | санузел сух и не жарко — вытяжка не нужна | ✅ (T086) |

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
