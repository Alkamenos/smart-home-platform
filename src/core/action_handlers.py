"""
Action Handlers for Smart Home Platform.

This module provides action functions that return CommandIntent objects
instead of directly calling Home Assistant services. This allows FSMs
to remain decoupled from HA implementation details.

Usage:
    registry = Registry()
    registry.register_action("turn_on_light", turn_on_light)
    registry.register_action("turn_off_light", turn_off_light)
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from .commands.dispatcher import CommandIntent


#: Яркость ночника в процентах (требование владельца 2026-10-09: «яркость 3%»).
NIGHTLIGHT_BRIGHTNESS_PCT = 3
#: Цвет ночника — чистый красный: убирает голубую часть спектра, которая будит.
NIGHTLIGHT_RGB_COLOR: tuple[int, int, int] = (255, 0, 0)


def extract_device_id(context: dict[str, Any]) -> str | None:
    """
    Extract device ID from context using fallback chain.

    Priority order:
    1. target_device_id (from FSM definition)
    2. entity_id (from event context)
    3. device_id (legacy fallback)

    Args:
        context: Context dictionary containing device identifiers.

    Returns:
        Device ID string or None if not found.
    """
    return context.get("target_device_id") or context.get("entity_id") or context.get("device_id")


def turn_on_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """
    Create a CommandIntent to turn on a light.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.

    Returns:
        CommandIntent to turn on the light, or None if entity_id is missing.
    """
    # Use target_device_id as primary source, fallback to entity_id
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("turn_on_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    source = context.get("source", "lighting")
    brightness_pct = context.get("brightness_pct")
    brightness = context.get("brightness")
    color_temp_kelvin = context.get("color_temp_kelvin")
    rgb_color = context.get("rgb_color")

    # Яркость и цвет задаются явно, а не «как помнит лампа»: без этого свет,
    # горевший ночником (красным на 3 %), включается потом тем же красным,
    # потому что прибор восстанавливает последние настройки (требование
    # владельца 2026-10-13). Что именно передать, решает поведение (params
    # манифеста); пустое значение означает «не трогать эту ось».
    data: dict[str, Any] = {}
    if brightness_pct is not None:
        data["brightness_pct"] = brightness_pct
    elif brightness is not None:
        data["brightness"] = brightness
    if color_temp_kelvin is not None:
        data["color_temp_kelvin"] = color_temp_kelvin
    elif rgb_color is not None:
        data["rgb_color"] = rgb_color

    logger.info(f"Creating turn_on_light intent for {entity_id}")

    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data=data,
        priority=priority,
        source=source,
    )


def turn_off_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """
    Create a CommandIntent to turn off a light.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.

    Returns:
        CommandIntent to turn off the light, or None if entity_id is missing.
    """
    # Use target_device_id as primary source, fallback to entity_id
    entity_id = extract_device_id(context)

    if not entity_id:
        logger.warning("turn_off_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    source = context.get("source", "lighting")
    # Пометку ставит движок для событий расписания: выключение по часам обязано
    # пройти, даже если человек вечером трогал этот свет.
    bypass_lockout = bool(context.get("bypass_lockout", False))

    logger.info(f"Creating turn_off_light intent for {entity_id}")

    return CommandIntent(
        bypass_lockout=bypass_lockout,
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=priority,
        source=source,
    )


def turn_on_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """
    Create a CommandIntent to turn on a night light: 3% и красный.

    Требование владельца (2026-10-09): пока включён модификатор «мы спим»,
    ночник даёт 3% яркости чистым красным (255, 0, 0) — яркий свет ночью
    сбивает циркадные ритмы, а красный почти не даёт голубой части спектра.
    Значения меняются через манифест (``brightness_pct``, ``rgb_color``);
    прежний параметр ``brightness`` (0–255) уважается, если задан явно.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.

    Returns:
        CommandIntent to turn on the night light, or None if entity_id is missing.
    """
    # Use target_device_id as primary source, fallback to entity_id
    entity_id = extract_device_id(context)

    if not entity_id:
        logger.warning("turn_on_night_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    source = context.get("source", "night_light")

    data: dict[str, Any] = {}
    if context.get("brightness_pct") is not None:
        data["brightness_pct"] = context["brightness_pct"]
    elif context.get("brightness") is not None:
        # Прежний параметр в шкале 0–255 — уважается, но дефолт теперь в
        # процентах: HA принимает brightness_pct напрямую и без перевода.
        data["brightness"] = context["brightness"]
    else:
        data["brightness_pct"] = NIGHTLIGHT_BRIGHTNESS_PCT
    if context.get("rgb_color"):
        data["rgb_color"] = context["rgb_color"]
    else:
        data["rgb_color"] = list(NIGHTLIGHT_RGB_COLOR)

    # Всё, что уйдёт в Home Assistant, печатается целиком: утром по журналу
    # должно быть видно, каким именно светом включён ночник.
    logger.info(f"Creating turn_on_night_light intent for {entity_id} data={data}")

    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data=data,
        priority=priority,
        source=source,
    )


def turn_off_night_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """
    Create a CommandIntent to turn off a night light.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.

    Returns:
        CommandIntent to turn off the night light, or None if entity_id is missing.
    """
    # Use target_device_id as primary source, fallback to entity_id
    entity_id = extract_device_id(context)

    if not entity_id:
        logger.warning("turn_off_night_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    source = context.get("source", "night_light")

    logger.info(f"Creating turn_off_night_light intent for {entity_id}")

    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_off",
        data={},
        priority=priority,
        source=source,
    )


def release_device(state: Any, context: dict) -> None:
    """
    Освобождает устройство от захвата FSM.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing dispatcher, target_device_id, and source.
    """
    dispatcher = context.get("dispatcher")
    entity_id = extract_device_id(context)
    source = context.get("source")

    if dispatcher and entity_id and source:
        dispatcher.release(entity_id, source)
        logger.info(f"Released device {entity_id} from {source}")
    else:
        logger.warning(
            f"release_device: Missing dispatcher={dispatcher}, "
            f"entity_id={entity_id}, or source={source}"
        )


def _climate_intent(
    context: dict[str, Any],
    service: str,
    source: str,
    *,
    hvac_mode: str | None = None,
) -> CommandIntent | None:
    """Собрать команду климатического устройства.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.
        hvac_mode: Режим кондиционера, если его нужно задать явно.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None

    data: dict[str, Any] = {}
    # Имя параметра в манифесте — `target_temp`; прежнее чтение `target_temperature`
    # означало, что команда всегда уходила без температуры, сколько бы её ни задали
    # в конфигурации (#71). Старое имя оставлено как запасной вариант: им пользуются
    # вызовы вне контекста поведения.
    target_temperature = context.get("target_temp")
    if target_temperature is None:
        target_temperature = context.get("target_temperature")
    if target_temperature is not None:
        data["temperature"] = target_temperature

    # Режим кондиционера: `cool` для охлаждения, `dry` для осушения. Общая
    # ось с `set_temperature`: у кондиционера один режим на комнату, и два
    # автомата, дергающие его попеременно, выглядели бы как поломка.
    mode = hvac_mode if hvac_mode is not None else context.get("hvac_mode")
    if mode is not None and not isinstance(mode, bool):
        data["hvac_mode"] = mode

    logger.info(f"Создаю команду {service} для {entity_id}, данные: {data}")

    return CommandIntent(
        device_id=entity_id,
        domain="climate",
        service=service,
        data=data,
        priority=context.get("priority", 50),
        source=source,
        # Кондиционер, включённый зимой с пульта, выключается даже если
        # платформа считает устройство занятым: включение зимой портит технику
        # (FR-015), и блокировка тут была бы препятствием, а не защитой.
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


def ac_dry_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить осушение кондиционером.

    Осушение — отдельный режим `dry` того же кондиционера, а не второй
    устройство: режим у него один, и переключение с охлаждения на осушение
    меняет ``hvac_mode`` (FR-017).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``humidity_threshold``.

    Returns:
        Команда ``climate.set_hvac_mode`` либо ``None``.
    """
    del state
    return _climate_intent(context, "set_hvac_mode", "ac_dry_on", hvac_mode="dry")


def ac_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить кондиционер.

    Нужен для возврата из режимов охлаждения и осушения в обогрев: пока
    кондиционер работает, обогреватель платформа включает не будет — два
    источника тепла в одной комнате.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда ``climate.turn_off`` либо ``None``.
    """
    del state
    return _climate_intent(context, "turn_off", "ac_off")


def ac_set_mode(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Переключить режим кондиционера.

    Режим меняется только при фактическом изменении потребности: у кондиционера
    сигналит при каждой смене режима (FR-016, требование владельца), поэтому
    «просто отправить на каждое показание датчика» — недопустимо.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``hvac_mode``.

    Returns:
        Команда ``climate.set_hvac_mode`` либо ``None``.
    """
    del state
    mode = context.get("hvac_mode")
    if mode is None or isinstance(mode, bool):
        logger.warning("ac_set_mode: режим не задан — переключать нечем")
        return None
    return _climate_intent(context, "set_hvac_mode", "ac_set_mode")


#: Сколько минут обогреватель работает по одному решению, если в манифесте дли��ость
#: не задана (минуты).
#:
#: Значение по умолчанию подобрано так, чтобы обогреватель успевал набрать
#: температуру, но не работал вхолостую, если датчик показывает, что уже достигнуто.
#: Каждое следующее решение принимается по свежему показанию датчика.
DEFAULT_HEATER_RUN_MINUTES = 15


def _heater_intent(
    context: dict[str, Any],
    domain: str,
    service: str,
    source: str,
    data: dict[str, Any] | None = None,
    target_entity_id: str | None = None,
) -> CommandIntent | None:
    """Собрать команду обогревателю в его собственном домене.

    Обогреватель — это `switch.*` с таймером `number.*`, а не `climate.*`:
    команды для кондиционера и термостатов тут не годятся, Home Assistant их
    отвергнет, и отказ выглядел бы как «устройство не отвечает».

    Args:
        context: Контекст перехода с ``entity_id`` обогревателя.
        domain: Домен команды: ``number`` для таймера, ``switch`` для включения.
        service: Сервис Home Assistant.
        source: Источник для аудита и блокировок; по нему видно, каким путём
            пошла команда — через таймер или без него.
        data: Дополнительные поля команды.
        target_entity_id: Сущность, которой адресована команда. По умолчанию —
            сам обогреватель, но для ``number.set_value`` это должен быть таймер:
            Home Assistant не найдёт ``switch.*`` в домене ``number`` и откажет,
            а платформа сочтёт команду отправленной.

    Returns:
        Команда либо ``None``, если обогреватель не указан.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id обогревателя в контексте")
        return None
    logger.info(
        f"Создаю команду {domain}.{service} для {target_entity_id or entity_id}, "
        f"данные: {data or {}}"
    )
    return CommandIntent(
        device_id=target_entity_id or entity_id,
        domain=domain,
        service=service,
        data=data or {},
        priority=context.get("priority", 50),
        source=source,
        # Признак обхода блокировки едет из события: движок ставит его для
        # событий из SAFETY_EVENTS (`engine.py:126-128`). Без этого суточное
        # событие не погасило бы обогреватель, включённый человеком, а
        # «ручное вмешательство переживает автоматику» держалось бы случайно.
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


#: Сколько секунд в одной минуте. Таймер обогревателя измеряется в секундах, а
#: решения платформы принимаются в минутах, поэтому перевод стоит в одной точке.
SECONDS_PER_MINUTE = 60

#: Единицы измерения, которые таймер обогревателя может иметь. Значение
#: сравнивается приведённым к нижнему регистру и без пробелов: Home Assistant
#: пишет ``s``, ``sec``, ``min`` по-разному в зависимости от интеграции, и
#: несовпадение регистра не должно молча возвращаться к минутам.
_TIMER_UNIT_ALIASES: dict[str, str] = {
    "s": "s",
    "sec": "s",
    "secs": "s",
    "second": "s",
    "seconds": "s",
    "мин": "min",
    "min": "min",
    "mins": "min",
    "minute": "min",
    "minutes": "min",
}

#: Единица по умолчанию, когда устройство её не назвало. Минуты, а не секунды:
#: исторически платформа отправляла минуты, и если бы дефолт был другим, дома
#: с молчаливо неизвестной единицей получили бы час работы вместо получаса.
DEFAULT_TIMER_UNIT = "min"


def normalize_timer_unit(unit: Any) -> str | None:
    """Привести единицу измерения таймера к канону: ``s`` или ``min``.

    Args:
        unit: Единица как её назвало устройство, из манифеста или Home Assistant.

    Returns:
        ``"s"``, ``"min"`` либо ``None``, если единица не распознана.
    """
    if not isinstance(unit, str):
        return None
    return _TIMER_UNIT_ALIASES.get(unit.strip().lower())


def _timer_duration(context: dict[str, Any]) -> tuple[float, str]:
    """Перевести длительность работы в единицу измерения таймера.

    Боевой дефект 2026-10-11: платформа отправляла ``run_minutes`` (15) прямо в
    ``number.set_value``, а таймер обогревателя измеряется в секундах. Home
    Assistant принимала значение, обогреватель включался и гас через 15 секунд —
    а автомат честно отрабатывал свой таймер и выходил по ``timeout``. Итог:
    обогрев не работал сутки, и ни один признак это не показывал.

    Args:
        context: Контекст перехода с ``run_minutes`` и, возможно, ``timer_unit``.

    Returns:
        Пара ``(значение, единица)``. При нераспознанной единице возвращаются
        минуты и пометка ``assumed_unit`` в данных — угадывание обязано быть
        видимым, иначе тот же баг вернётся на другом устройстве.
    """
    minutes = context.get("run_minutes", DEFAULT_HEATER_RUN_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        minutes = DEFAULT_HEATER_RUN_MINUTES

    unit = normalize_timer_unit(context.get("timer_unit"))
    assumed = unit is None
    if unit is None:
        unit = DEFAULT_TIMER_UNIT

    value = float(minutes) * SECONDS_PER_MINUTE if unit == "s" else float(minutes)
    # Таймер целочисленный (step 1), а `number.set_value` на дробном значении
    # отвергается: значение округляется к тому, что устройство умеет.
    if float(value).is_integer():
        value = int(value)
    return value, unit if not assumed else DEFAULT_TIMER_UNIT


def timer_assumption_flag(unit: str, assumed: bool) -> str | None:
    """Пометка угаданной единицы для данных команды.

    Args:
        unit: Единица, по которой посчитано значение.
        assumed: Единица была угадана, а не прочитана.

    Returns:
        ``"min"``, если единица угадана, иначе ``None``.
    """
    return unit if assumed else None


def heater_timer_on(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Включить обогреватель на заданное время через его собственный таймер.

    Требование владельца (FR-004): обогреватель включается «на 15 минут», а не
    просто «включить». Пока идёт таймер обогревателя, платформа не обязана
    ничего решать; когда таймер истечёт, придёт новое показание датчика и
    решение будет принято заново. Так обогреватель не может остаться включённым
    навсегда, даже если датчик температуры перестанет отвечать.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``, ``heater_timer`` и ``run_minutes``.

    Returns:
        Шаги команды по порядку: прибор включается, затем таймер. Если таймер в
        манифесте не задан — единственный шаг включения; без обогревателя —
        пустой список.
    """
    del state
    timer = context.get("heater_timer")
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("heater_timer_on: нет entity_id обогревателя в контексте")
        return []

    minutes = context.get("run_minutes", DEFAULT_HEATER_RUN_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        minutes = DEFAULT_HEATER_RUN_MINUTES

    if not timer:
        logger.warning(
            f"Обогреватель {entity_id} включается без таймера: таймер не задан в "
            "манифесте, выключит датчик. Если датчик откажет, обогреватель "
            "останется работать — это защита, которой у нас больше нет"
        )
        return _single_step(_heater_intent(context, "switch", "turn_on", "heater_on_no_timer"))

    value, unit = _timer_duration(context)
    # В данных команды — только `value`. Служебные поля (`timer_unit`,
    # `assumed_unit`) Home Assistant отвергает с 400 Bad Request: у сервиса
    # `number.set_value` нет таких параметров. Проверено в доме 2026-10-11 —
    # вместе с лишним ключом не применялся весь таймер, то есть обогрев
    # включался и гас без всякой защиты. Такая отметка нужна журналу, а не
    # устройству, поэтому она живёт в намерении и в предупреждении ниже.
    data: dict[str, Any] = {"value": value}
    assumed_unit = timer_assumption_flag(
        unit, normalize_timer_unit(context.get("timer_unit")) is None
    )
    if assumed_unit:
        logger.warning(
            f"{entity_id}: единица измерения таймера {context.get('timer_unit')!r} "
            f"не распознана, приняты {assumed_unit}. Если устройство измеряет "
            "таймер в секундах, обогреватель выключится через минуты вместо "
            "получаса — задайте timer_unit в манифесте"
        )

    # Порядок обязателен и выяснен в доме (2026-10-11): таймер принимается
    # только на уже включённом приборе. Таймер, записанный на выключенный
    # обогреватель, Home Assistant сохраняет без ошибки, а греть никто не
    # будет — отказ выглядит как успех, и обогрев молчит.
    on_step = _heater_intent(context, "switch", "turn_on", "heater_timer_on")
    timer_step = _heater_intent(
        context,
        "number",
        "set_value",
        "heater_timer_on",
        data=data,
        # Адресат — таймер, а не переключатель: `number.set_value` для
        # `switch.*` Home Assistant отвергает, и команда пропала бы молча.
        target_entity_id=timer,
    )
    # Единица измерения — сведения для разбора, а не параметр сервиса: в `data`
    # она даёт 400 Bad Request и вместе с собой уносит весь таймер.
    if timer_step is not None:
        timer_step.timer_unit = unit
    return _with_requirement([on_step, timer_step], timer_step, "on", state_entity=entity_id)


def _single_step(intent: CommandIntent | None) -> list[CommandIntent]:
    """Обернуть одно намерение в список шагов.

    Args:
        intent: Намерение либо ``None``.

    Returns:
        Список из одного намерения либо пустой список.
    """
    return [intent] if intent is not None else []


def _with_requirement(
    steps: list[CommandIntent | None],
    guarded: CommandIntent | None,
    required_state: str,
    state_entity: str | None = None,
) -> list[CommandIntent]:
    """Пометить шаг условием по состоянию прибора, выбросив пустые шаги.

    Args:
        steps: Шаги команды по порядку.
        guarded: Шаг, который отправляется только при нужном состоянии прибора.
        required_state: Ожидаемое состояние прибора (``on``/``off``).
        state_entity: Прибор, состояние которого проверяется. По умолчанию —
            адресат шага, но для таймера это должен быть сам обогреватель:
            состояние таймера — это «сколько секунд осталось», а не вкл/выкл.

    Returns:
        Готовые к отправке шаги.
    """
    result = [step for step in steps if step is not None]
    for step in result:
        if step is guarded:
            step.requires_state = required_state
            if state_entity:
                step.state_entity = state_entity
    return result


def heater_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить обогреватель напрямую, без его таймера.

    Отдельное действие нужно для домов, где таймера нет вовсе, и для ручной
    правки поведения; решение «через таймер или напрямую» принимает
    `heater_timer_on`, а этот путь оставлен явным.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя.

    Returns:
        Команда включения либо ``None`` без обогревателя.
    """
    del state
    return _heater_intent(context, "switch", "turn_on", "heater_on")


def heater_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Выключить обогреватель: цель достигнута или время работы вышло.

    Порядок тот же, что и при включении, только наоборот: сначала таймер в ноль,
    затем выключение. Таймер, оставленный на выключенном приборе, включит его
    позже сам — обогреватель загорается через несколько минут после того, как
    платформа решила, что комната достаточно тёплая.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.

    Returns:
        Шаги выключения по порядку.
    """
    del state
    return _heater_off_steps(context, "heater_off", emergency=False)


def heater_emergency_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Выключить обогреватель принудительно — минуя блокировку.

    Вызывается по истечении страховочного таймера: автомат отработал положенное
    время, а нового решения не принял никто, потому что датчик молчит или отказал.

    Блокировка обходится намеренно. Блокировка отвечает на вопрос «не мешай ли
    человеку», и человек, включивший обогреватель руками, вправе получить его
    выключенным по таймеру автоматики. Обратное неверно: в бою 2026-10-11
    блокировка оставила масляный радиатор включённым на пять часов после
    истечения таймера, потому что датчик комнаты перестал присылать показания.
    Защита от неудобства не должна превращаться в открытый обогрев.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.

    Returns:
        Шаги выключения по порядку.
    """
    del state
    return _heater_off_steps(context, "heater_emergency_off", emergency=True)


def _heater_off_steps(
    context: dict[str, Any],
    source: str,
    emergency: bool,
) -> list[CommandIntent]:
    """Шаги выключения обогревателя: таймер в ноль, затем прибор.

    Требования состояния здесь намеренно нет. Чтобы выключить прибор, он должен
    быть **включён**, а требование ``off`` делало бы команду неотправляемой
    никогда: прибор, который и так выключен, прошёл бы проверку, а включённый
    остался бы греться.

    Args:
        context: Контекст с ``entity_id`` обогревателя и, возможно, таймером.
        source: Источник для аудита и блокировок.
        emergency: Обойти ли блокировку ручного вмешательства.

    Returns:
        Шаги выключения по порядку.
    """
    timer = context.get("heater_timer")
    emergency_ctx = {**context, "bypass_lockout": True} if emergency else context
    off_step = _heater_intent(emergency_ctx, "switch", "turn_off", source)
    if not timer or off_step is None:
        return _single_step(off_step)

    zero_step = _heater_intent(
        emergency_ctx,
        "number",
        "set_value",
        source,
        data={"value": 0, "timer_unit": "s"},
        target_entity_id=timer,
    )
    return [step for step in (zero_step, off_step) if step is not None]


def ac_cool_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить охлаждение кондиционером на потолок комфорта.

    Охлаждать платформа умеет только до той температуры, которую владелец назвал
    комфортной (`comfort_max`). Охлаждать «прохладнее» без его решения — значит
    перестудить дом и получить ту же жалобу, с которой начиналось: слишком жарко
    или слишком холодно, но не по вашему слову.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` кондиционера и ``comfort_max``.

    Returns:
        Команда ``climate.set_temperature`` либо ``None``, если нет кондиционера
        или потолка комфорта.
    """
    del state
    comfort_max = context.get("comfort_max")
    if comfort_max is None or isinstance(comfort_max, bool):
        logger.warning("ac_cool_on: нет потолка комфорта — охлаждать не к чему")
        return None
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("ac_cool_on: нет entity_id кондиционера в контексте")
        return None
    # Потолок комфорта едет в команду именно как температура: `_climate_intent`
    # читает `target_temp`, и без подстановки `climate.set_temperature` ушёл бы
    # без неё — как в дефекте #71, только наоборот (там терялось заданное, здесь
    # не подставлялось рассчитанное).
    return _climate_intent(
        {**context, "target_temp": comfort_max},
        "set_temperature",
        "ac_cool_on",
    )


def ac_forced_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Немедленно выключить кондиционер — защита зимой.

    Кондиционер, работающий на охлаждение при отрицательной температуре, повреждает
    компрессор (FR-011). Поэтому зимой любая команда его включения гасится сразу,
    а владелец получает уведомление: молча выключенный кондиционер выглядит как
    «платформа решила не охлаждать», и поломку техники никто не заметит.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` кондиционера.

    Returns:
        Команда ``climate.turn_off`` либо ``None`` без кондиционера.
    """
    del state
    return _climate_intent(context, "turn_off", "ac_forced_off")


def climate_heat(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить отопление на заданную температуру.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``target_temperature``.

    Returns:
        Команда установки температуры либо ``None`` без устройства.
    """
    return _climate_intent(context, "set_temperature", "climate_heat")


def climate_cool(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить охлаждение на заданную температуру.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``target_temperature``.

    Returns:
        Команда установки температуры либо ``None`` без устройства.
    """
    return _climate_intent(context, "set_temperature", "climate_cool")


def climate_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить климатическое устройство.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда выключения либо ``None`` без устройства.
    """
    return _climate_intent(context, "turn_off", "climate_off")


def _fan_intent(
    context: dict[str, Any],
    service: str,
    source: str,
    keys: tuple[str, ...] = (),
) -> CommandIntent | None:
    """Собрать команду вентилятора.

    ``keys`` перечисляет поля, которые **разрешено** положить в данные команды
    именно этой услуги. Собирать все известные поля подряд нельзя: у сервисов
    Home Assistant строгая схема, и лишний ключ роняет команду целиком — HA
    отвечает ``400 Bad Request``. Так ``fan.set_preset_mode`` с подмешанным
    ``percentage`` не применялся вовсе, и рекуператор оставался в прежнем режиме,
    пока платформа считала, что переключила его (боевой разбор 2026-10-12).

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.
        keys: Поля контекста, допустимые в данных этой услуги.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None

    data: dict[str, Any] = {key: context[key] for key in keys if context.get(key) is not None}

    logger.info(f"Создаю команду {service} для {entity_id}, данные: {data}")

    return CommandIntent(
        device_id=entity_id,
        domain="fan",
        service=service,
        data=data,
        priority=context.get("priority", 50),
        source=source,
    )


def fan_turn_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить вентилятор.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и, необязательно, ``percentage``.

    Returns:
        Команда включения либо ``None`` без устройства.
    """
    return _fan_intent(context, "turn_on", "fan_turn_on", keys=("percentage",))


def fan_turn_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить вентилятор.

    Данных нет вовсе: ``fan.turn_off`` скорости не принимает, а лишний ключ
    (например, накопленный ``percentage``) роняет команду с 400.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда выключения либо ``None`` без устройства.
    """
    return _fan_intent(context, "turn_off", "fan_turn_off")


def fan_set_percentage(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Задать скорость вентилятора.

    Скорость — отдельная ось рекуператора и не зависит от режима (FR-020,
    FR-021). В данных команды лежит **ровно** ``percentage``: лишний ключ в
    команде Home Assistant отвергает с 400 Bad Request, и вместе с ним теряется
    вся команда.

    Скорость задаётся сервисом ``fan.turn_on`` с процентом, а не
    ``fan.set_percentage``: у боевого рекуператора последний врёт — на живых
    замерах 2026-10-12 запрос 14 давал 100 %, запрос 71 не применялся вовсе,
    тогда как ``fan.turn_on`` с процентом ставил нужную ступень надёжно и не
    сбивал режим (research.md D24). Оба сервиса — стандартные сервисы Home
    Assistant, ``fan.turn_on`` с ``percentage`` заодно гарантирует, что прибор
    включён (скорость у выключенного рекуператора не принимается).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``percentage`` (0–100).

    Returns:
        Команда скорости либо ``None`` без устройства или значения.
    """
    del state
    percentage = context.get("percentage")
    if percentage is None or isinstance(percentage, bool):
        logger.warning("fan_set_percentage: нет процента скорости в контексте")
        return None
    try:
        value = int(percentage)
    except (TypeError, ValueError):
        logger.warning(f"fan_set_percentage: процент не число: {percentage!r}")
        return None
    if not 0 <= value <= 100:
        logger.warning(f"fan_set_percentage: процент {value} вне диапазона 0–100")
        return None

    return _fan_intent(
        {**context, "percentage": value},
        "turn_on",
        "fan_set_percentage",
        keys=("percentage",),
    )


def fan_set_preset(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Задать режим вентилятора.

    Режим выбирается из списка самого устройства (``research.md`` D7):
    «Приток», «Рекуперация (зима)» и другие. Платформа физику не считает — она
    выбирает то, что умеет прибор.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``preset_mode``.

    Returns:
        Команда режима либо ``None`` без устройства или названия режима.
    """
    del state
    preset_mode = context.get("preset_mode") or context.get("chosen_mode")
    if not isinstance(preset_mode, str) or not preset_mode.strip():
        logger.warning("fan_set_preset: нет названия режима в контексте")
        return None

    return _fan_intent(
        {**context, "preset_mode": preset_mode},
        "set_preset_mode",
        "fan_set_preset",
        keys=("preset_mode",),
    )


def fan_airing_on(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Включить проветривание: режим максимального притока (``mode_airing``).

    Отдельное действие, а не общий ``fan_set_preset``: имя режима проветривания
    лежит в собственном параметре ``mode_airing``, и подставлять его в условие
    было бы нельзя — условие не меняет контекст, а действие его не сохраняет
    между переходами. Иначе переиспользованное имя режима пережило бы
    проветривание и следующий переход поставил бы «Приток MAX» вместо обычного
    режима (боевой урок: состояние накопительное, research.md D17).

    Действие для ВХОДА в ``AIRING``: прибор мог быть выключен, поэтому он ещё и
    включается. Подтверждение уже работающего прибора — ``fan_airing_reassert``.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``mode_airing``.

    Returns:
        Шаги: включение прибора, затем режим максимального притока.
    """
    del state
    mode = context.get("mode_airing")
    if not isinstance(mode, str) or not mode.strip():
        logger.warning("fan_airing_on: нет режима проветривания (mode_airing) в контексте")
        return []
    # Прибор может быть выключен (владелец выключал вентиляцию, рекуператор
    # остался off): одного режима мало — прибор надо ещё и включить. Включение
    # уходит с процентом 100: без него интеграция меняет атрибуты, но прибор не
    # запускает. И идёт оно ПЕРВЫМ, а режим — последним: включение с процентом
    # сбрасывает режим прибора на базовый, поэтому «последнее слово» должно быть
    # за режимом (боевой разбор 2026-10-13: прибор возвращался в «Рекуперацию»
    # через пару минут после нашей пары команд).
    power = _fan_intent(
        {**context, "percentage": 100}, "turn_on", "fan_airing_on", keys=("percentage",)
    )
    preset = _fan_intent(
        {**context, "preset_mode": mode}, "set_preset_mode", "fan_airing_on", keys=("preset_mode",)
    )
    return [step for step in (power, preset) if step is not None]


def fan_airing_reassert(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Подтвердить режим максимального притока, НЕ трогая включение.

    Нужно в состоянии ``AIRING``: прибор уже работает, и его надо лишь удержать
    на «Притоке MAX». Включение с процентом здесь нельзя — прибор обрабатывает
    его с задержкой и переключается на базовый режим, «соскакивая» с максимума
    (боевой разбор 2026-10-13: через 17 секунд после подтверждения прибор снова
    стоял на «Рекуперации (зиме)»). Сам «Приток MAX» форсирует 100, поэтому
    скорости не нужно.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``mode_airing``.

    Returns:
        Команда режима либо ``None`` без устройства или названия режима.
    """
    del state
    mode = context.get("mode_airing")
    if not isinstance(mode, str) or not mode.strip():
        logger.warning("fan_airing_reassert: нет режима проветривания (mode_airing) в контексте")
        return None
    return _fan_intent(
        {**context, "preset_mode": mode},
        "set_preset_mode",
        "fan_airing_reassert",
        keys=("preset_mode",),
    )


def fan_apply_mode_and_speed(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Задать режим и скорость — двумя независимыми командами.

    У рекуператора это две независимые оси (FR-021), и смена скорости не должна
    сбрасывать режим. Одной командой обе не задать: у сервисов Home Assistant
    нет общего вызова, а значит порядок — «режим, затем скорость».

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``, ``preset_mode`` и ``percentage``.

    Returns:
        Два шага: режим, затем скорость.
    """
    del state
    mode_step = fan_set_preset(None, context)
    speed_step = fan_set_percentage(None, context)
    return [step for step in (mode_step, speed_step) if step is not None]


def _cover_intent(context: dict[str, Any], service: str, source: str) -> CommandIntent | None:
    """Собрать команду шторы.

    В данных — ничего, кроме сущности: ``cover.open_cover`` и
    ``cover.close_cover`` параметров не принимают, а лишний ключ Home Assistant
    отвергает с 400 Bad Request (research.md D23). Движением прибора платформа
    не управляет — она только просит открыть или закрыть.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant (``open_cover`` или ``close_cover``).
        source: Источник для аудита и блокировок.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None
    logger.info(f"Создаю команду {service} для {entity_id}")
    return CommandIntent(
        device_id=entity_id,
        domain="cover",
        service=service,
        data={},
        priority=context.get("priority", 50),
        source=source,
    )


def cover_open(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Открыть штору.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда открытия либо ``None`` без устройства.
    """
    return _cover_intent(context, "open_cover", "cover_open")


def cover_close(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Закрыть штору.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда закрытия либо ``None`` без устройства.
    """
    return _cover_intent(context, "close_cover", "cover_close")


def exhaust_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить вытяжку.

    Вытяжка санузла — прибор без скорости: только вкл/выкл (``research.md``,
    таблица устройств). Команда уходит без данных: ``turn_on`` сервису ничего
    не нужно, а лишний ключ отвергается с 400 Bad Request.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда либо ``None`` без устройства.
    """
    del state
    return _fan_intent(context, "turn_on", "exhaust_on")


def exhaust_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить вытяжку.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда либо ``None`` без устройства.
    """
    del state
    return _fan_intent(context, "turn_off", "exhaust_off")


def _modifier_off_intent(
    context: dict[str, Any], entity_key: str, source: str
) -> CommandIntent | None:
    """Собрать команду снятия модификатора владельца (``input_boolean.turn_off``).

    Модификаторы «проветривание» и «вытяжка» выключаются только в Home
    Assistant: у платформы нет своего хранилища желаний владельца. Сущность
    берётся из доменных правил дома (``automation_rules.ventilation``), которые
    фабрика кладёт в параметры поведения: ``airing_entity`` для проветривания,
    ``exhaust_entity`` для вытяжки.

    ``input_boolean.turn_off`` идемпотентен: если модификатор уже снят, прибор
    не изменится.

    Args:
        context: Контекст перехода.
        entity_key: Имя ключа контекста с сущностью модификатора.
        source: Источник для аудита.

    Returns:
        Команда записи либо ``None``, если сущность не задана.
    """
    entity_id = context.get(entity_key)
    if not isinstance(entity_id, str) or not entity_id:
        logger.warning(f"{source}: нет сущности модификатора ({entity_key}) в контексте")
        return None

    logger.info(f"Создаю команду input_boolean.turn_off для {entity_id} ({source})")
    return CommandIntent(
        device_id=entity_id,
        domain="input_boolean",
        service="turn_off",
        data={},
        priority=context.get("priority", 50),
        source=source,
    )


def airing_after_timeout(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Проветривание кончилось: вернуть обычный режим и снять модификатор.

    У перехода ровно одно действие (конституция I), поэтому «вернуть обычный
    режим» и «снять модификатор» — список шагов одного действия. Снятие
    модификатора идёт **последним**: обычный режим должен встать до того, как
    Home Assistant пришлёт событие ``airing_on = false`` и состояние
    пересчитается (FR-024, FR-025, T085).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``preset_mode``/``percentage`` и ``airing_entity``.

    Returns:
        Шаги: обычный режим и скорость, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = list(fan_apply_mode_and_speed(None, context))
    reset = _modifier_off_intent(context, "airing_entity", "airing_reset")
    if reset is not None:
        steps.append(reset)
    return steps


def exhaust_after_timeout(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Вытяжка по модификатору кончилась: погасить прибор и снять модификатор.

    Если вытяжку включил сам санузел (температура или влажность), следующее
    событие датчика включит её снова — модификатор здесь ни при чём. Снятие
    модификатора убирает ручную причину, а не единственную (T085, T086).

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` вытяжки и ``exhaust_entity``.

    Returns:
        Шаги: выключение вытяжки, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = []
    off = exhaust_off(None, context)
    if off is not None:
        steps.append(off)
    reset = _modifier_off_intent(context, "exhaust_entity", "exhaust_reset")
    if reset is not None:
        steps.append(reset)
    return steps


def airing_off(state: Any, context: dict[str, Any]) -> list[CommandIntent]:
    """Прервать проветривание: погасить вентиляцию и снять модификатор.

    Запасной путь таймера: обычный режим вернуть нельзя (нет улицы, работает
    обогрев, выключил владелец), поэтому прибор гасится, а модификатор
    снимается — иначе проветривание продлилось бы само на следующем показании
    датчика.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` и ``airing_entity``.

    Returns:
        Шаги: выключение вентиляции, затем снятие модификатора.
    """
    del state
    steps: list[CommandIntent] = []
    off = fan_turn_off(None, context)
    if off is not None:
        steps.append(off)
    reset = _modifier_off_intent(context, "airing_entity", "airing_reset")
    if reset is not None:
        steps.append(reset)
    return steps


# Dictionary of all available action handlers for easy registration
ACTION_HANDLERS: dict[str, Any] = {
    "turn_on_light": turn_on_light,
    "turn_off_light": turn_off_light,
    "turn_on_night_light": turn_on_night_light,
    "turn_off_night_light": turn_off_night_light,
    "release_device": release_device,
    # Климат и вентиляция. Шаблоны climate_control и humidity_ventilation
    # ссылались на эти действия, но они не были зарегистрированы: движок
    # отклонял переход, а платформа выглядела исправной.
    "climate_heat": climate_heat,
    "climate_cool": climate_cool,
    "climate_off": climate_off,
    # Обогрев комнат по датчику (спека 011). Обогреватель — это `switch.*` с
    # таймером `number.*`, поэтому у него свои действия: команда таймеру вместо
    # `climate.set_temperature`, который адресован кондиционерам и термостатам.
    "heater_timer_on": heater_timer_on,
    "heater_on": heater_on,
    "heater_off": heater_off,
    "heater_emergency_off": heater_emergency_off,
    "ac_cool_on": ac_cool_on,
    "ac_set_mode": ac_set_mode,
    "ac_dry_on": ac_dry_on,
    "ac_off": ac_off,
    "ac_forced_off": ac_forced_off,
    "fan_turn_on": fan_turn_on,
    "fan_turn_off": fan_turn_off,
    "fan_set_percentage": fan_set_percentage,
    "fan_set_preset": fan_set_preset,
    "fan_airing_on": fan_airing_on,
    "fan_airing_reassert": fan_airing_reassert,
    "fan_apply_mode_and_speed": fan_apply_mode_and_speed,
    "exhaust_on": exhaust_on,
    "exhaust_off": exhaust_off,
    "airing_after_timeout": airing_after_timeout,
    "airing_off": airing_off,
    "exhaust_after_timeout": exhaust_after_timeout,
    # Шторы (спека 015).
    "cover_open": cover_open,
    "cover_close": cover_close,
}


def register_all_actions(registry: Any) -> None:
    """
    Register all action handlers in the given registry.

    Args:
        registry: Registry instance to register actions in.
    """
    for name, handler in ACTION_HANDLERS.items():
        registry.register_action(name, handler)
    logger.info(f"Registered {len(ACTION_HANDLERS)} action handlers")
