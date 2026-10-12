"""Пересмотр вентиляции при смене переключателя — сквозная проверка.

Спека 014, боевой разбор 2026-10-12. Переключатели вентиляции (выключатель
владельца, сезон, модификаторы) меняются в Home Assistant, а автомат вентиляции
слушает только `temperature_changed`. Пока датчик комнаты молчал, выключение
вентиляции не действовало, а смена сезона не пересобирала режим.

Проверка идёт на настоящих объектах движка, роутера и фабрики — не подменой:
нас интересуют соединения между модулями (`EventRouter.route_settings_change`
шлёт `settings_changed`, шаблон на этот триггер пересматривает решение).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.registry import Registry


SENSOR = "sensor.datchik_temperatury_kabinet_temperature"
FAN = "fan.base_smart"
HEATER = "switch.obogrevatel_kabinet"
ROOM = "kabinet"
PRIORITY = 10
FAN_FSM = f"{FAN}_ventilation_modes_{PRIORITY}"
HEATER_FSM = f"{HEATER}_climate_control_{PRIORITY}"

SUPPLY_PARAMS: dict[str, Any] = {
    "ventilation_role": "supply",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 42,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
}

CLIMATE_PARAMS: dict[str, Any] = {
    "hysteresis": 0.5,
    "run_minutes": 15,
    "heater_timer": "number.obogrevatel_kabinet_countdown",
}


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в HA."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            Всегда True.
        """
        self.intents.append(intent)
        return True

    def services(self) -> list[str]:
        """Сервисы всех команд, что дошли до диспетчера.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]

    def presets(self) -> list[Any]:
        """Запрошенные режимы рекуператора.

        Returns:
            Список значений `preset_mode`.
        """
        return [i.data.get("preset_mode") for i in self.intents if i.service == "set_preset_mode"]


def _manifest() -> Manifest:
    """Манифест из одной комнаты: датчик, рекуператор и обогреватель.

    Обогреватель нужен, чтобы у комнаты был климат-автомат: по нему роутер
    считает `heating_active` — теперь признак диагностический, и проверка
    убеждается, что сам по себе он вентиляцию больше не гасит (FR-055).

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[
            RoomConfig(
                id=ROOM,
                name="Кабинет",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(SUPPLY_PARAMS),
                            )
                        ],
                    ),
                    DeviceConfig(
                        id=HEATER,
                        type="climate",
                        behaviors=[
                            BehaviorConfig(
                                template="climate_control",
                                priority=PRIORITY,
                                params=dict(CLIMATE_PARAMS),
                            )
                        ],
                    ),
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать боевой конвейер: движок, роутер и помнящий команды диспетчер.

    Returns:
        Движок, роутер и диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    manifest = _manifest()
    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RecordingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


def _state(engine: FSMEngine, fsm: str) -> str:
    """Текущее состояние автомата.

    Args:
        engine: Движок с автоматами.
        fsm: Идентификатор автомата.

    Returns:
        Имя состояния.
    """
    state = engine.get_state(fsm)
    assert state is not None
    return state.current_state


_winter = {"outside_temperature": 5.0, "is_winter": True, "comfort_max": 25.0}


@pytest.mark.asyncio
async def test_owner_switch_off_stops_running_recuperator() -> None:
    """Выключение владельца гасит работающий рекуператор без показания датчика.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_state_change(
        entity_id=SENSOR, new_state="20.0", old_state="19.9", context=dict(_winter)
    )
    assert _state(engine, FAN_FSM) == "SUPPLY"

    dispatcher.intents.clear()
    await router.route_settings_change({**_winter, "ventilation_on": False})

    assert _state(engine, FAN_FSM) == "IDLE", (
        "выключатель владельца не погасил работающий рекуператор: он ждёт "
        "показания датчика, которого может не быть часами (боевой дефект)"
    )
    assert "turn_off" in dispatcher.services()


@pytest.mark.asyncio
async def test_owner_switch_on_starts_ventilation() -> None:
    """Включение владельца запускает вентиляцию зимой в режиме рекуперации.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_settings_change({**_winter, "ventilation_on": True})

    assert _state(engine, FAN_FSM) == "SUPPLY"
    assert dispatcher.presets() == ["Рекуперация (зима)"], (
        "зимой выбран не режим рекуперации: сырой приток остужает дом"
    )


async def test_cold_room_blocks_ventilation_start_on_settings_change() -> None:
    """Комната холоднее уставки — пересмотр не включает вентиляцию (FR-049).

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_settings_change(
        {**_winter, "ventilation_on": True, "temperature": 20.0, "climate_setpoint": 22.5}
    )

    assert _state(engine, FAN_FSM) == "IDLE", (
        "пересмотр включил вентиляцию в комнате холоднее уставки: приток унёс бы "
        "тепло, которое платформа только что потратила (FR-049)"
    )
    assert dispatcher.intents == []


@pytest.mark.asyncio
async def test_heating_no_longer_blocks_ventilation() -> None:
    """Работающий обогрев больше не гасит вентиляцию сам по себе (FR-055).

    Право на вентиляцию определяет уставка: если комната выше уставки, обогрев
    вентиляции не мешает.

    Returns:
        Ничего.
    """
    engine, router, _ = _build()
    state = engine.get_state(HEATER_FSM)
    assert state is not None
    state.current_state = "HEATING"

    await router.route_settings_change(
        {**_winter, "ventilation_on": True, "temperature": 24.0, "climate_setpoint": 22.5}
    )

    assert _state(engine, FAN_FSM) == "SUPPLY", (
        "обогрев всё ещё гасит вентиляцию: правило по обогреву заменено правилом "
        "по уставке (FR-055), а комната 24 °C выше уставки 22.5"
    )


@pytest.mark.asyncio
async def test_season_change_reselects_mode_while_running() -> None:
    """Смена сезона на работающем рекуператоре пересобирает режим.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_state_change(
        entity_id=SENSOR, new_state="20.0", old_state="19.9", context=dict(_winter)
    )
    assert _state(engine, FAN_FSM) == "SUPPLY"

    dispatcher.intents.clear()
    await router.route_settings_change(
        {"outside_temperature": 20.0, "is_winter": False, "comfort_max": 25.0}
    )

    assert dispatcher.presets() == ["Рекуперация (лето)"], (
        "смена сезона не сменила режим: прибор остался бы в зимнем режиме до "
        "следующего показания датчика"
    )
