# Контракты: климат и вентиляция (спека 014)

**Дата**: 2026-10-10. Контракты проверяемы: каждое объявление сверяется с
загрузкой манифеста и сентинелем состава
(`tests/unit/core/test_builtin_guards_actions.py:331`).

---

## 1. Ключи контекста

Читаются из Home Assistant адаптером, попадают в словарь перехода через
существующий путь (`ha_adapter.py:1473-1488` → `event_router.py:190` →
`engine.py:1095`). Механизм — тот же, что у `daylight` и `sleep_modifier_on`.

| Ключ | Тип | Может быть `None` | Что означает `None` |
|------|-----|-------------------|---------------------|
| `climate_setpoint` | `float` | да | уставка не прочитана — решения нет |
| `comfort_max` | `float` | да | потолок не прочитан — охлаждение не разрешено |
| `is_winter` | `bool` | да | сезон неизвестен — кондиционер **не** включаем |
| `climate_enabled` | `bool` | да | флаг не прочитан — только наблюдение |
| `ac_allowed` | `bool` | да | гейт не прочитан — охлаждение не разрешено |
| `ventilation_enabled` | `bool` | да | флаг не прочитан — только наблюдение |
| `ventilation_on` | `bool` | да | выключалка не прочитана — решение не принимаем |
| `airing_on` | `bool` | да | то же |
| `exhaust_on` | `bool` | да | то же |
| `outside_temperature` | `float` | да | скорость не пересчитываем (FR-029) |

**Правило безопасности**: неизвестное значение (`None`) никогда не читается как
«разрешено». Для `is_winter` неизвестный сезон запрещает кондиционер (FR-014) —
включить его зимой дороже, чем летом погреть день лишний раз.

### Граница влияния отказа (FR-046)

Отказ одного сигнала не должен гасить то, что от него не зависит:

| Отказало | Что продолжает работать | Почему |
|----------|-------------------------|--------|
| `outside_temperature` | обогрев по комнатам | обогрев от улицы не зависит: решение по комнате и цели |
| `temperature` комнаты | остальные комнаты, вентиляция | комната исключается, дом не останавливается |
| `climate_setpoint` | вентиляция | уставка обогрева не участвует в выборе режима |
| `sleep_modifier_on` | обогрев | «мы спим» ограничивает яркий свет, а не отопление (FR-011) |
| `ventilation_on` | обогрев, охлаждение | выключалка вентиляции не касается климата |

**Проверяется одним тестом на каждую строку таблицы**, а не только в бою:
дешёво, и регрессия ловится до поездки в дом.

---

## 2. Новые условия

Каждое условие — функция `(state, context) -> bool` с обязательным
`deny_reason`, возвращающим имя из `GUARD_DENIAL_REASONS`
(`engine.py:839-871`).

| Имя | Разрешает, когда | Требуемые данные | Причина отказа |
|-----|------------------|------------------|----------------|
| `may_heat` | обогреватель можно включить (FR-002, FR-007, FR-008, FR-040) | `temperature` | `climate_disabled`, `managed_by_hardware`, `setpoint_unavailable`, `not_cold_enough` |
| `may_stop_heating` | цель достигнута, обогреватель можно выключить (FR-003) | `temperature` | `guard_data_missing` |
| `may_cool` | кондиционер можно включать (FR-013, FR-017) | `temperature` | `ac_not_allowed`, `ac_forbidden_in_winter`, `not_above_comfort` |
| `mode_for_weather` | режим рекуператора выбран (FR-019) | — | `outside_temp_missing` |
| `speed_within_limits` | скорость в допустимых границах (FR-020, FR-022, FR-027, FR-034) | `outside_temperature` | `ventilation_disabled`, `turned_off_by_owner` |
| `owner_wants_airing` | проветривание запрошено (FR-024) | — | — |
| `sensor_is_alive` | датчик отвечает (FR-045, FR-047) | — | `sensor_stale` |

### Объявление требуемых данных (FR-039)

```python
GUARD_DATA_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "humidity_above_60": ("humidity",),
    "humidity_below_60": ("humidity",),
    "may_heat": ("temperature",),  # новое
    "may_stop_heating": ("temperature",),  # новое
    "may_cool": ("temperature",),  # новое
    "speed_within_limits": ("outside_temperature",),  # новое
}
```

**Осторожно** (`research.md` D1): объявлять `climate_setpoint` в `requires`
нельзя. `_is_measurement` (`engine.py:103-104`) считает любое число
пригодным измерением, включая `95.0`, и движок вернёт `guard_data_missing`
раньше, чем отработает `deny_reason` с причиной `setpoint_unavailable`. Уставка
проверяется внутри условия.

### Отказ по отсутствию данных

`_guard_rejection_reason` (`engine.py:761-806`) проверяет данные **до** вызова
условия и возвращает `guard_data_missing` — отдельную причину от «значение не
подходит». Это уже различает молчащий датчик и штатную работу; фича обязана этим
пользоваться, а не заводить свои коды (FR-038).

**Границы объявления**:

| Ключ | Объявлять в `requires` | Почему |
|------|-----------------------|--------|
| `temperature` | да | пригодное измерение; при отсутствии — `guard_data_missing` (FR-009) |
| `outside_temperature` | да | то же |
| `humidity` | да (уже сделано) | то же |
| `climate_setpoint` | **нет** | любое число прошло бы как измерение, включая `95.0`, и отказ «уставка вне диапазона» стал бы недостижим |
| `sleep_modifier_on` | **нет** | булево; `False` значит «не спим», а «неизвестно» — третье состояние |
| `room`, `managed_by_hardware` | **нет** | не измерения, а параметры поведения |

Проверка FR-012 (потолок комфорта) и FR-023 (причина ночного ограничения) идёт
внутри условий, а не через `requires`: обе величины приходят из глобальных
сущностей и могут отсутствовать как «неизвестно», что не то же, что «ноль».

**FR-047** (ограничение повторов) не относится к условиям: это поведение
журнала и диспетчера. Реализуется на стороне записи отказов, а не в
`deny_reason`, и проверяется счётом записей в минуту (SC-016).

---

## 3. Новые действия

Все — `domain`/`service` Home Assistant, `device_id` из
`extract_device_id` (`action_handlers.py:32-47`).

| Имя | Домен | Сервис | `data` | Назначение |
|-----|-------|--------|--------|-----------|
| `fan_set_percentage` | `fan` | `set_percentage` | `{percentage: 0-100}` | FR-020 |
| `fan_set_preset` | `fan` | `set_preset_mode` | `{preset_mode: str}` | FR-019 |
| `fan_apply_mode_and_speed` | `fan` | два намерения | оба | FR-021 |
| `exhaust_on` | `fan` | `turn_on` | — | FR-026, FR-028 |
| `exhaust_off` | `fan` | `turn_off` | — | FR-026 |
| `ac_cool_to` | `climate` | `set_temperature` | `{temperature: float}` | FR-013 |
| `ac_set_mode` | `climate` | `set_hvac_mode` | `{hvac_mode: str}` | FR-016 |

### Регистрация — четыре места

| Где | Что |
|-----|-----|
| `action_handlers.py:551` | запись в `ACTION_HANDLERS` |
| `CONTRACT.yaml` | `registered_actions` (регенерация через `tools/gen_template_contract.py:147`) |
| `test_template_contract.py:163` | сверка контракта с реестром — упадёт сама |
| `test_builtin_guards_actions.py:372` | сверка действий манифеста с реестром |

### Порядок команд (FR-021)

Очереди нет: `submit` вызывает Home Assistant немедленно
(`dispatcher.py:199-204`). При равном приоритете обе команды проходят
(строгое `>` на `:170`), порядок — по доставке. Режим и скорость уходят двумя
командами подряд; атомарности в системе нет, и спека этого не обещает.

**Почему не один сервис**: Home Assistant не имеет «режим и скорость» одним
вызовом для `fan`. Скрывать это означало бы считать, будто атомарность есть.

### `bypass_lockout` (FR-007, D11)

Климатические и вентиляционные действия заполняют `bypass_lockout` из
контекста. Сейчас `_heater_intent` (`action_handlers.py:282-317`) его не
заполняет, и обход блокировки работает только для `turn_off_light`.

Правило: заполняется **только** для событий из `SAFETY_EVENTS`
(`engine.py:126-128`). Ручное вмешательство владельца блокировку обходит, а
собственная команда платформы — нет, иначе платформа не уважала бы ручное
действие.

---

## 4. Параметры манифеста

Объявление обязательно: неописанный параметр отвергается веб-интерфейсом
(`behavior_params.py:88-94`).

### `automation_rules.climate`

| Поле | Тип | По умолчанию |
|------|-----|--------------|
| `setpoint_entity` | `str \| None` | `input_number.temperatura` |
| `comfort_max_entity` | `str \| None` | `input_number.maksimalno_komfortnaia_temperatura` |
| `season_entity` | `str \| None` | `input_boolean.zima` |
| `feature_entity` | `str \| None` | `input_boolean.feature_climate` |
| `ac_gate_entity` | `str \| None` | `input_boolean.ispolzovat_konditsioner` |
| `setpoint_min` | `float` | 5.0 |
| `setpoint_max` | `float` | 30.0 |

### `automation_rules.ventilation`

| Поле | Тип | По умолчанию |
|------|-----|--------------|
| `feature_entity` | `str \| None` | `input_boolean.feature_ventilation` |
| `enable_entity` | `str \| None` | `input_boolean.ventiliatsiia` |
| `airing_entity` | `str \| None` | `input_boolean.provetrivanie` |
| `exhaust_entity` | `str \| None` | `input_boolean.provetrivanie_vytyazhka` |
| `outside_temp_entity` | `str \| None` | `sensor.temperatura_na_ulitse_srednee` |
| `manual_lockout_min` | `int` | 15 |

### Параметры поведения

См. `data-model.md`, разделы 4 и 5. Все — с диапазонами и значениями по
умолчанию; диапазон проверяется валидатором манифеста.

---

## 5. Что происходит при нарушении контракта

| Нарушение | Поведение |
|-----------|-----------|
| Сущность в манифесте не отвечает | ключ `None`, причина в журнале, решения нет |
| Пустая строка в `*_entity` | ошибка загрузки манифеста |
| Уставка вне диапазона | отказ `setpoint_unavailable` |
| Показание `unavailable` | отказ `guard_data_missing`, комната исключена |
| Параметр вне диапазона | ошибка валидации манифеста |
| Режим отсутствует в списке устройства | команда не отправляется, причина в журнале |
| Действие в реестре отсутствует | **ошибка загрузки** (D8), не предупреждение |
| Событие без слушателей | обычное состояние платформы |

Последняя строка важна для приёмки: `template_lifecycle_events` в `CONTRACT.yaml`
помечает события, которые платформа публикует, но ни один шаблон не слушает.
Каждое новое событие климата и вентиляции должно быть услышано хотя бы одним
шаблоном, иначе оно попадёт в этот список.
