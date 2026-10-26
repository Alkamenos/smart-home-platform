"""Публичный фасад действий платформы (B80).

Действия разложены по доменам в ``core/actions``. Здесь остаются реестр
``ACTION_HANDLERS`` и ``register_all_actions``; имена реэкспортируются, чтобы
прежние импорты ``from core.action_handlers import ...`` продолжали работать.

Usage:
    registry = Registry()
    registry.register_action("turn_on_light", turn_on_light)
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from core.actions.climate import (
    _TIMER_UNIT_ALIASES,
    DEFAULT_HEATER_RUN_MINUTES,
    DEFAULT_TIMER_UNIT,
    SECONDS_PER_MINUTE,
    _climate_intent,
    _heater_intent,
    _heater_off_steps,
    _single_step,
    _timer_duration,
    _with_requirement,
    ac_cool_on,
    ac_dry_on,
    ac_forced_off,
    ac_off,
    ac_set_mode,
    climate_cool,
    climate_heat,
    climate_off,
    heater_emergency_off,
    heater_off,
    heater_on,
    heater_timer_on,
    normalize_timer_unit,
    timer_assumption_flag,
)
from core.actions.common import extract_device_id, release_device
from core.actions.covers import _cover_intent, cover_close, cover_open
from core.actions.lighting import (
    NIGHTLIGHT_BRIGHTNESS_PCT,
    NIGHTLIGHT_RGB_COLOR,
    _global_color_temp,
    turn_off_light,
    turn_off_night_light,
    turn_on_light,
    turn_on_night_light,
)
from core.actions.ventilation import (
    _fan_intent,
    _modifier_off_intent,
    airing_after_timeout,
    airing_off,
    exhaust_after_timeout,
    exhaust_off,
    exhaust_on,
    fan_airing_on,
    fan_airing_reassert,
    fan_apply_mode_and_speed,
    fan_set_percentage,
    fan_set_preset,
    fan_turn_off,
    fan_turn_on,
)


__all__ = [
    "ACTION_HANDLERS",
    "DEFAULT_HEATER_RUN_MINUTES",
    "DEFAULT_TIMER_UNIT",
    "NIGHTLIGHT_BRIGHTNESS_PCT",
    "NIGHTLIGHT_RGB_COLOR",
    "SECONDS_PER_MINUTE",
    "_TIMER_UNIT_ALIASES",
    "_climate_intent",
    "_cover_intent",
    "_fan_intent",
    "_global_color_temp",
    "_heater_intent",
    "_heater_off_steps",
    "_modifier_off_intent",
    "_single_step",
    "_timer_duration",
    "_with_requirement",
    "ac_cool_on",
    "ac_dry_on",
    "ac_forced_off",
    "ac_off",
    "ac_set_mode",
    "airing_after_timeout",
    "airing_off",
    "climate_cool",
    "climate_heat",
    "climate_off",
    "cover_close",
    "cover_open",
    "exhaust_after_timeout",
    "exhaust_off",
    "exhaust_on",
    "extract_device_id",
    "fan_airing_on",
    "fan_airing_reassert",
    "fan_apply_mode_and_speed",
    "fan_set_percentage",
    "fan_set_preset",
    "fan_turn_off",
    "fan_turn_on",
    "heater_emergency_off",
    "heater_off",
    "heater_on",
    "heater_timer_on",
    "normalize_timer_unit",
    "register_all_actions",
    "release_device",
    "timer_assumption_flag",
    "turn_off_light",
    "turn_off_night_light",
    "turn_on_light",
    "turn_on_night_light",
]


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
