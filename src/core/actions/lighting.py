"""Действия света: включение, выключение и ночник."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.actions.common import extract_device_id
from core.commands.dispatcher import CommandIntent


#: Яркость ночника в процентах (требование владельца 2026-10-09: «яркость 3%»).
NIGHTLIGHT_BRIGHTNESS_PCT = 3
#: Цвет ночника — чистый красный: убирает голубую часть спектра, которая будит.
NIGHTLIGHT_RGB_COLOR: tuple[int, int, int] = (255, 0, 0)

#: Яркость вечернего света без движения, если манифест не задал свою.
DIM_BRIGHTNESS_PCT = 3


def _light_domain(entity_id: str) -> str:
    """Домен команды: лампа или выключатель.

    В манифесте встречаются светильники, которые Home Assistant отдаёт как
    `switch.*` (подсветка зеркала). Для них нельзя звать `light.turn_on`:
    сервис другого домена прибор не включит.

    Args:
        entity_id: Сущность прибора.

    Returns:
        ``"switch"`` для выключателей, иначе ``"light"``.
    """
    return "switch" if entity_id.startswith("switch.") else "light"


def _global_color_temp(context: dict[str, Any]) -> int | None:
    """Текущая цветовая температура дома для включения света.

    Порядок: текущее значение (``color_temp_current``) → дневная или ночная
    граница по ``daylight``. Значение приходит из Home Assistant числом; если
    его нет, глобальная температура не навязывается — лампа останется при своей.

    Args:
        context: Контекст перехода.

    Returns:
        Целое значение в Кельвинах либо ``None``.
    """
    candidates = [
        context.get("color_temp_current"),
        context.get("color_temp_day")
        if context.get("daylight")
        else context.get("color_temp_night"),
        context.get("color_temp_night")
        if context.get("daylight")
        else context.get("color_temp_day"),
    ]
    for candidate in candidates:
        if candidate is None or isinstance(candidate, bool):
            continue
        try:
            return int(round(float(candidate)))
        except (TypeError, ValueError):
            continue
    return None


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
    domain = _light_domain(entity_id)
    brightness_pct = context.get("brightness_pct")
    brightness = context.get("brightness")
    color_temp_kelvin = context.get("color_temp_kelvin")
    rgb_color = context.get("rgb_color")

    # Глобальная цветовая температура: поведение `lighting` включает флаг
    # `use_global_color_temp`, и тогда температуру берём из общего значения дома.
    # Явный параметр устройства сильнее — им можно закрепить особую лампу.
    if color_temp_kelvin is None and context.get("use_global_color_temp"):
        color_temp_kelvin = _global_color_temp(context)

    # Яркость и цвет задаются явно, а не «как помнит лампа»: без этого свет,
    # горевший ночником (красным на 3 %), включается потом тем же красным,
    # потому что прибор восстанавливает последние настройки (требование
    # владельца 2026-10-13). Что именно передать, решает поведение (params
    # манифеста); пустое значение означает «не трогать эту ось». Выключателю
    # яркость и цвет не передаются: у него только on/off.
    data: dict[str, Any] = {}
    if domain == "light":
        if brightness_pct is not None:
            data["brightness_pct"] = brightness_pct
        elif brightness is not None:
            data["brightness"] = brightness
        if color_temp_kelvin is not None:
            try:
                data["color_temp_kelvin"] = int(round(float(color_temp_kelvin)))
            except (TypeError, ValueError):
                data["color_temp_kelvin"] = color_temp_kelvin
        elif rgb_color is not None:
            data["rgb_color"] = rgb_color

    logger.info(f"Creating turn_on_light intent for {entity_id}")

    return CommandIntent(
        device_id=entity_id,
        domain=domain,
        service="turn_on",
        data=data,
        priority=priority,
        source=source,
        # Плановый свет включает владелец своим флагом, а не удобство
        # автоматики: ручная блокировка не должна отменять его решение.
        # Остальные шаблоны флаг не задают, и поведение для них прежнее.
        bypass_lockout=bool(context.get("bypass_lockout", False)),
    )


def turn_on_dim_light(state: Any, context: dict[str, Any]) -> CommandIntent | None:
    """Включить вечерний свет на минимальной яркости.

    Движение включает полную яркость, а без движения свет не гаснет: он
    остаётся тусклым (по умолчанию 3 %) с общей температурой дома. Это не
    ночник: цвет не красный, а тот, что задаёт глобальная кривая.

    Args:
        state: Текущее состояние автомата (не используется).
        context: Контекст с ``entity_id`` и параметрами яркости/температуры.

    Returns:
        Команда включения либо ``None`` без устройства.
    """
    entity_id = extract_device_id(context)
    if not entity_id:
        logger.warning("turn_on_dim_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    brightness = context.get("dim_brightness_pct", DIM_BRIGHTNESS_PCT)
    try:
        brightness_pct = int(brightness)
    except (TypeError, ValueError):
        brightness_pct = DIM_BRIGHTNESS_PCT

    data: dict[str, Any] = {
        "brightness_pct": brightness_pct,
        # Плавно, но быстро: 100 % → 3 % не должно выглядеть как вспышка.
        "transition": 2,
    }
    color_temp_kelvin = context.get("color_temp_kelvin")
    if color_temp_kelvin is None and context.get("use_global_color_temp"):
        color_temp_kelvin = _global_color_temp(context)
    if color_temp_kelvin is not None:
        try:
            data["color_temp_kelvin"] = int(round(float(color_temp_kelvin)))
        except (TypeError, ValueError):
            data["color_temp_kelvin"] = color_temp_kelvin

    logger.info(f"Creating turn_on_dim_light intent for {entity_id} data={data}")

    return CommandIntent(
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data=data,
        priority=priority,
        source=context.get("source", "lighting_dim"),
    )


def turn_off_light(
    state: Any, context: dict[str, Any]
) -> CommandIntent | list[CommandIntent] | None:
    """
    Create a CommandIntent to turn off a light.

    Для лампы с ночником (параметр ``prepare_for_night``) перед выключением
    ставится ночной режим — 3 % красного. Прибор запоминает последнее состояние
    и при следующем включении восстанавливает его: без этой подготовки ночник
    сначала вспыхивал бы прошлой яркой яркостью (замечание владельца 2026-10-21).
    Если свет включат днём, действие включения явно ставит нужную яркость и
    цвет — прошлое состояние не переживёт команду.

    Args:
        state: Current FSM state (not used for this action).
        context: Context dictionary containing entity_id and other parameters.

    Returns:
        CommandIntent to turn off the light, a pair «ночной режим → выключение»
        для лампы с ночником, or None if entity_id is missing.
    """
    # Use target_device_id as primary source, fallback to entity_id
    entity_id = extract_device_id(context)

    if not entity_id:
        logger.warning("turn_off_light: No entity_id in context")
        return None

    priority = context.get("priority", 50)
    source = context.get("source", "lighting")
    domain = _light_domain(entity_id)
    # Пометку ставит движок для событий расписания: выключение по часам обязано
    # пройти, даже если человек вечером трогал этот свет.
    bypass_lockout = bool(context.get("bypass_lockout", False))

    logger.info(f"Creating turn_off_light intent for {entity_id}")

    off_intent = CommandIntent(
        bypass_lockout=bypass_lockout,
        device_id=entity_id,
        domain=domain,
        service="turn_off",
        data={},
        priority=priority,
        source=source,
    )
    # Подготовка к ночнику — только для лампы: у выключателя нет яркости/цвета.
    if domain != "light" or not context.get("prepare_for_night"):
        return off_intent

    # Последнее состояние перед выключением — ночник. Следующее включение
    # восстановит 3 % красного, а не прошлую яркую яркость.
    night_intent = CommandIntent(
        bypass_lockout=bypass_lockout,
        device_id=entity_id,
        domain="light",
        service="turn_on",
        data={
            "brightness_pct": NIGHTLIGHT_BRIGHTNESS_PCT,
            "rgb_color": list(NIGHTLIGHT_RGB_COLOR),
            "transition": 0,
        },
        priority=priority,
        source="lighting_prepare_night",
        skip_if={"state": "on", "brightness_pct": NIGHTLIGHT_BRIGHTNESS_PCT},
        requires_state="on",
    )
    logger.info(f"Prepare {entity_id} for night before turn_off")
    return [night_intent, off_intent]


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
