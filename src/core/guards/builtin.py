"""Встроенные guard'ы: реестр и требования к данным (BACKLOG B80).

Здесь остались две вещи: **сборка реестра** (``build_guards``, ``register_all_guards``)
и требования к данным. Сами условия разошлись по домам: ``context`` — общее чтение
контекста, время и суточные окна; ``lighting`` — свет; ``climate`` — климат;
``ventilation`` — вентиляция; ``covers`` — шторы.

Каждый guard — фабрика, возвращающая функцию ``(state, context) -> bool``.
Фабрика, а не обычная функция, потому что guard'ам нужны сервисы: трекер
ручного вмешательства и диапазон дня. Обычная функция не смогла бы их получить
из реестра, который хранит только функции.

Общий принцип — **отказ при нехватке данных**. Если нет значения датчика или
идентификатора устройства, переход запрещается: разрешить автоматику вслепую
хуже, чем не включить свет.

Имена, переехавшие в соседние модули, реэкспортируются отсюда: тот, кто
импортировал guard из ``builtin``, продолжает работать — разрез не менял
контракта.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from core.guards.climate import (
    _colder_than_setpoint as _colder_than_setpoint,
    _cooling_applicable as _cooling_applicable,
    _cooling_denial as _cooling_denial,
    _drying_denial as _drying_denial,
    _heating_denial as _heating_denial,
    _not_cold_enough_reason as _not_cold_enough_reason,
    make_at_or_above_setpoint as make_at_or_above_setpoint,
    make_below_setpoint as make_below_setpoint,
    make_climate_is_enabled as make_climate_is_enabled,
    make_humidity_above as make_humidity_above,
    make_humidity_below as make_humidity_below,
    make_managed_by_hardware_ok as make_managed_by_hardware_ok,
    make_may_cool as make_may_cool,
    make_may_dry as make_may_dry,
    make_may_heat as make_may_heat,
    make_may_stop_heating as make_may_stop_heating,
)
from core.guards.context import (
    DEFAULT_DAY_END_MINUTES as DEFAULT_DAY_END_MINUTES,
    DEFAULT_DAY_START_MINUTES as DEFAULT_DAY_START_MINUTES,
    DEFAULT_DAY_TIME_RANGE as DEFAULT_DAY_TIME_RANGE,
    DEFAULT_EXHAUST_HUMIDITY as DEFAULT_EXHAUST_HUMIDITY,
    DEFAULT_EXHAUST_TEMPERATURE as DEFAULT_EXHAUST_TEMPERATURE,
    DEFAULT_HUMIDITY_THRESHOLD as DEFAULT_HUMIDITY_THRESHOLD,
    DEFAULT_HYSTERESIS as DEFAULT_HYSTERESIS,
    DEFAULT_MOTION_ECHO_SEC as DEFAULT_MOTION_ECHO_SEC,
    DEFAULT_QUIET_FROM as DEFAULT_QUIET_FROM,
    DEFAULT_QUIET_TO as DEFAULT_QUIET_TO,
    DEFAULT_SPEED_COLD_GAIN as DEFAULT_SPEED_COLD_GAIN,
    DEFAULT_SPEED_COLD_REFERENCE as DEFAULT_SPEED_COLD_REFERENCE,
    DEFAULT_SPEED_MIN as DEFAULT_SPEED_MIN,
    DEFAULT_SPEED_NORMAL as DEFAULT_SPEED_NORMAL,
    DEFAULT_WINTER_THRESHOLD as DEFAULT_WINTER_THRESHOLD,
    HOUSE_TZ as HOUSE_TZ,
    MAX_SETPOINT as MAX_SETPOINT,
    MAX_SPEED as MAX_SPEED,
    MIN_SETPOINT as MIN_SETPOINT,
    MIN_SPEED as MIN_SPEED,
    REGISTERED_GUARDS as REGISTERED_GUARDS,
    _comfort_max_value as _comfort_max_value,
    _context_zone as _context_zone,
    _dark_enough as _dark_enough,
    _humidity_value as _humidity_value,
    _hysteresis_value as _hysteresis_value,
    _is_night as _is_night,
    _motion_echo_window as _motion_echo_window,
    _motion_is_echo as _motion_is_echo,
    _now_in as _now_in,
    _now_utc as _now_utc,
    _number as _number,
    _parse_hhmm as _parse_hhmm,
    _resolve_house_tz as _resolve_house_tz,
    _room_temperature as _room_temperature,
    _setpoint_value as _setpoint_value,
    _temperature_value as _temperature_value,
    _threshold as _threshold,
    _ventilation_role as _ventilation_role,
    make_device_is_off as make_device_is_off,
    make_device_is_on as make_device_is_on,
    make_has_usable_reading as make_has_usable_reading,
    make_is_day_time as make_is_day_time,
    make_is_night_time as make_is_night_time,
    make_sensor_is_alive as make_sensor_is_alive,
    make_startup_reapply as make_startup_reapply,
    with_requirements as with_requirements,
)
from core.guards.covers import (
    _cover_close_reason as _cover_close_reason,
    make_covers_should_close as make_covers_should_close,
    make_covers_should_open as make_covers_should_open,
)
from core.guards.lighting import (
    make_is_manual_override_enabled as make_is_manual_override_enabled,
    make_may_stay_idle as make_may_stay_idle,
    make_may_turn_on as make_may_turn_on,
    make_modifier_is_on as make_modifier_is_on,
    make_stops_on_sleep as make_stops_on_sleep,
    make_stops_on_sunrise as make_stops_on_sunrise,
)
from core.guards.ventilation import (
    _bathroom_is_uncomfortable as _bathroom_is_uncomfortable,
    _choose_normal_mode as _choose_normal_mode,
    _clamp_speed as _clamp_speed,
    _room_is_above_comfort as _room_is_above_comfort,
    _speed_from_context as _speed_from_context,
    _ventilation_allowed as _ventilation_allowed,
    make_airing_should_end as make_airing_should_end,
    make_exhaust_should_stop as make_exhaust_should_stop,
    make_mode_for_weather as make_mode_for_weather,
    make_owner_wants_airing as make_owner_wants_airing,
    make_should_run_exhaust as make_should_run_exhaust,
    make_should_run_max_supply as make_should_run_max_supply,
    make_speed_within_limits as make_speed_within_limits,
    make_ventilation_should_stop as make_ventilation_should_stop,
)


logger = logging.getLogger(__name__)

#: Порог влажности по умолчанию. Зашит в именах guard'ов
#: (``humidity_above_60``), поэтому используется, когда параметр не задан.

#: Диапазон дня по умолчанию. Дополняет ночное расписание ``23:00-07:00``
#: из манифеста; переопределяется через ``DAY_TIME_RANGE``.


#: Часовой пояс дома, разрешённый один раз при импорте.

#: Окно тишины по умолчанию: с этого часа движение не включает свет.

#: Границы дня для запасного решения, когда состояние солнца ещё неизвестно.

#: До этого часа (включительно) движение свет не включает.


#: Окно, в котором движение считается эхом нашего же выключения света
#: (параметр поведения `motion_echo_sec`).


#: Имена guard'ов, которым нужны данные датчиков, и сами данные. Ключ — имя
#: условия, значение — ключи контекста перехода, без которых решение выносить
#: не по чему, и отказ должен называться «данных нет», а не «значение не подходит».
GUARD_DATA_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "humidity_above_60": ("humidity",),
    "humidity_below_60": ("humidity",),
    # Климат объявляет только показание. Уставку добавлять нельзя: любое число
    # прошло бы как измерение, включая 95.0, и движок вернул бы «данных нет»
    # прежде, чем условие успело сказать «уставка вне диапазона» — а разные
    # причины в журнале означают разное: «датчик молчит» и «уставка негодна».
    "may_heat": ("temperature",),
    "mode_for_weather": ("outside_temperature",),
    "should_run_max_supply": ("temperature",),
    # Температура комнаты приходит под именем роли `temperature`, а не под
    # `source_room_temperature`: прежний ключ никто не писал, и объявленное
    # требование останавливало условие на «данных нет» при живом датчике.
    # Отсутствие температуры называет само условие причиной `sensor_stale`.
    "speed_within_limits": ("outside_temperature",),
    "sensor_is_alive": ("outside_temperature",),
    "may_stop_heating": ("temperature",),
    "has_usable_reading": ("temperature",),
    "may_cool": ("temperature",),
    "may_dry": ("humidity",),
}


def build_guards(
    control_tracker: Any,
    *,
    day_range: str = DEFAULT_DAY_TIME_RANGE,
    lockout_minutes: int = 60,
) -> dict[str, Callable[[Any, dict[str, Any]], bool]]:
    """Собрать все встроенные guard'ы для реестра.

    Args:
        control_tracker: Трекер ручного вмешательства.
        day_range: Диапазон дня для ``is_day_time``.
        lockout_minutes: Блокировка после ручного управления.

    Returns:
        Словарь «имя guard'а → функция». Имена совпадают с теми, что указаны в
        шаблонах ``src/features/*.yaml``.
    """
    guards: dict[str, Callable[[Any, dict[str, Any]], bool]] = {
        "is_day_time": make_is_day_time(day_range),
        "is_night_time": make_is_night_time(day_range),
        "is_manual_override_enabled": make_is_manual_override_enabled(
            control_tracker, lockout_minutes=lockout_minutes
        ),
        "humidity_above_60": make_humidity_above(),
        "humidity_below_60": make_humidity_below(),
        "may_turn_on": make_may_turn_on(),
        "modifier_is_on": make_modifier_is_on(),
        "below_setpoint": make_below_setpoint(),
        "at_or_above_setpoint": make_at_or_above_setpoint(),
        "climate_is_enabled": make_climate_is_enabled(),
        "managed_by_hardware_ok": make_managed_by_hardware_ok(),
        "stops_on_sleep": make_stops_on_sleep(),
        "stops_on_sunrise": make_stops_on_sunrise(),
        "may_heat": make_may_heat(),
        "mode_for_weather": make_mode_for_weather(),
        "should_run_max_supply": make_should_run_max_supply(),
        "airing_should_end": make_airing_should_end(),
        "startup_reapply": make_startup_reapply(),
        "device_is_off": make_device_is_off(),
        "device_is_on": make_device_is_on(),
        "speed_within_limits": make_speed_within_limits(),
        "covers_should_close": make_covers_should_close(),
        "covers_should_open": make_covers_should_open(),
        "owner_wants_airing": make_owner_wants_airing(),
        "should_run_exhaust": make_should_run_exhaust(),
        "exhaust_should_stop": make_exhaust_should_stop(),
        "ventilation_should_stop": make_ventilation_should_stop(),
        "sensor_is_alive": make_sensor_is_alive(),
        "may_cool": make_may_cool(),
        "may_dry": make_may_dry(),
        "may_stay_idle": make_may_stay_idle(),
        "may_stop_heating": make_may_stop_heating(),
        "has_usable_reading": make_has_usable_reading(),
    }
    # Требования объявляются здесь, рядом с условием: объявление в стороне
    # разошлось бы с ним при первом же переименовании.
    for name, requires in GUARD_DATA_REQUIREMENTS.items():
        guard = guards.get(name)
        if guard is not None:
            with_requirements(guard, *requires)
    return guards


#: Имена guard'ов, которые должны существовать в реестре движка.
#: Используется проверкой целостности: сверка с шаблонами по имени.
#: Гистерезис обогревателя по умолчанию, °C.
#:
#: Меньше — обогреватель дёргается на каждом градусе колебаний датчика, больше —
#: промахивается мимо комфорта и перегревает комнату. Полградуса — компромисс
#: между ними, и он же виден в поведении: обогреватель начинает работу заранее,
#: но не «дрожит» на границе.

#: Границы целевой температуры, °C.
#:
#: Уставка вне этих границ — поломка настройки, а не пожелание владельца:
#: 95 °C в комнате означает, что число пришло из другой сущности или из
#: неисправного сценария. Дальше этого климат не идёт: сначала в журнал, иначе
#: молчаливый перегрев.


#: Порог температуры улицы, ниже которого дом считается зимним. Значение по
#: умолчанию — 5 °C; это решение дома, а не свойство движка, поэтому оно
#: приходит параметром поведения.

#: Границы скорости рекуператора. Устройство принимает 0–100, и выход за них
#: означает либо отказ Home Assistant, либо молчаливое ограничение прибором.

#: Обычная скорость рекуператора, %. Боевой прибор (Vakio Base Smart) округляет
#: запрошенный процент **вверх** к ближайшей из своих семи ступеней
#: (14,29,43,57,71,86,100): запрос 43 попадает на ступень 57 %, а 42 — на 43 %
#: (research.md D24). Поэтому обычная скорость — 42, а не «номинальные» 43:
#: ступень 3 и есть задуманные ~43 %.

#: Минимальная скорость рекуператора, %. Ниже неё прибор работает впустую; это
#: решение дома, поэтому рабочее значение приходит параметром поведения
#: (``speed_min``), а это — запасное.

#: Температура улицы, °C, при которой скорость рекуператора обычная. Теплее —
#: обычная, холоднее — скорость падает: гнать морозный воздух в дом дороже, чем
#: сберечь тепло. Решение дома, поэтому рабочее значение — параметр
#: (``speed_cold_reference``).

#: На сколько процентов снижать скорость рекуператора на каждый градус улицы
#: ниже ``speed_cold_reference``. Рабочее значение — параметр (``speed_cold_gain``).

#: Порог температуры санузла, °C, с которого вытяжка считается нужной (T086).
#: Владелец выбрал 25 °C: зимой санузел держится на 23–24 °C, а выше — уже
#: заметный перегрев от печи или душа.

#: Порог влажности санузла, %, с которого вытяжка считается нужной (T086).
#: 65 % — тот же порог, что у прежнего шаблона humidity_ventilation.


def register_all_guards(registry: Any, control_tracker: Any) -> None:
    """Зарегистрировать встроенные guard'ы в реестре.

    Args:
        registry: Реестр движка.
        control_tracker: Трекер ручного вмешательства.
    """

    guards = build_guards(
        control_tracker,
        day_range=os.environ.get("DAY_TIME_RANGE", DEFAULT_DAY_TIME_RANGE),
    )
    for name, guard in guards.items():
        registry.register_guard(name, guard)
    logger.info(f"Registered {len(guards)} guards: {', '.join(sorted(guards))}")
