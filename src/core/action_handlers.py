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
    brightness = context.get("brightness")

    data: dict[str, Any] = {}
    if brightness is not None:
        data["brightness"] = brightness

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


def _climate_intent(context: dict[str, Any], service: str, source: str) -> CommandIntent | None:
    """Собрать команду климатического устройства.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.

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

    logger.info(f"Создаю команду {service} для {entity_id}")

    return CommandIntent(
        device_id=entity_id,
        domain="climate",
        service=service,
        data=data,
        priority=context.get("priority", 50),
        source=source,
    )


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

    Returns:
        Команда либо ``None``, если обогреватель не указан.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id обогревателя в контексте")
        return None
    return CommandIntent(
        device_id=entity_id,
        domain=domain,
        service=service,
        data=data or {},
        priority=context.get("priority", 50),
        source=source,
    )


def heater_timer_on(state: Any, context: dict[str, Any]) -> CommandIntent | None:
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
        Команда таймеру обогревателя либо команда включения, если таймер в
        манифесте не задан; ``None`` без обогревателя.
    """
    del state
    timer = context.get("heater_timer")
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("heater_timer_on: нет entity_id обогревателя в контексте")
        return None

    minutes = context.get("run_minutes", DEFAULT_HEATER_RUN_MINUTES)
    if isinstance(minutes, bool) or not isinstance(minutes, (int, float)) or minutes <= 0:
        minutes = DEFAULT_HEATER_RUN_MINUTES

    if not timer:
        logger.warning(
            f"Обогреватель {entity_id} включается без таймера: таймер не задан в "
            "манифесте, выключит датчик. Если датчик откажет, обогреватель "
            "останется работать — это защита, которой у нас больше нет"
        )
        return _heater_intent(context, "switch", "turn_on", "heater_on_no_timer")

    return _heater_intent(
        context,
        "number",
        "set_value",
        "heater_timer_on",
        data={"value": minutes},
    )


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


def heater_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить обогреватель: цель достигнута или время работы вышло.

    Args:
        state: Состояние автомата (не используется).
        context: Контекст с ``entity_id`` обогревателя.

    Returns:
        Команда выключения либо ``None`` без обогревателя.
    """
    del state
    return _heater_intent(context, "switch", "turn_off", "heater_off")


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


def _fan_intent(context: dict[str, Any], service: str, source: str) -> CommandIntent | None:
    """Собрать команду вентилятора.

    Args:
        context: Контекст перехода.
        service: Услуга Home Assistant.
        source: Источник для аудита и блокировок.

    Returns:
        CommandIntent либо ``None``, если устройство не указано.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning(f"{source}: нет entity_id в контексте")
        return None

    data: dict[str, Any] = {}
    for key in ("percentage", "preset_mode"):
        if context.get(key) is not None:
            data[key] = context[key]

    logger.info(f"Создаю команду {service} для {entity_id}")

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
    return _fan_intent(context, "turn_on", "fan_turn_on")


def fan_turn_off(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Выключить вентилятор.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id``.

    Returns:
        Команда выключения либо ``None`` без устройства.
    """
    return _fan_intent(context, "turn_off", "fan_turn_off")


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
    "ac_cool_on": ac_cool_on,
    "ac_forced_off": ac_forced_off,
    "fan_turn_on": fan_turn_on,
    "fan_turn_off": fan_turn_off,
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
