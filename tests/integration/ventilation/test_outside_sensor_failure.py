"""Отказ датчика улицы останавливает только скорость, а не всю вентиляцию (спека 014, T053, FR-046).

Проверка разделяет два решения:

- рекуператор без показания улицы **не выбирает** ни режим, ни скорость: зимой
  угадывание означало бы лишний приток свежего воздуха, летом — душный дом
  (FR-029);
- вытяжка санузла от улицы не зависит вовсе: высокая температура санузла
  включает её, даже когда улица недоступна. Отказ одного датчика не имеет права
  гасить соседнее решение (FR-046).

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


KABINET_TEMP = "sensor.datchik_temperatury_kabinet_temperature"
SANUZEL_TEMP = "sensor.datchik_temperatury_sanuzel_temperature"
SANUZEL_HUMIDITY = "sensor.datchik_vlazhnosti_sanuzel_humidity"
FAN = "fan.base_smart"
EXHAUST_FAN = "fan.vytyazhka_sanuzel"
PRIORITY = 10
SUPPLY_FSM = f"{FAN}_ventilation_modes_{PRIORITY}"
EXHAUST_FSM = f"{EXHAUST_FAN}_ventilation_modes_{PRIORITY}"

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

EXHAUST_PARAMS: dict[str, Any] = {
    "ventilation_role": "exhaust",
    "exhaust_temp_threshold": 25.0,
    "exhaust_humidity_threshold": 65.0,
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


def _manifest() -> Manifest:
    """Манифест из двух комнат: рекуператор в кабинете и вытяжка в санузле.

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
                id="kabinet",
                name="Кабинет",
                sensors={"temperature": KABINET_TEMP},
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
                    )
                ],
            ),
            RoomConfig(
                id="sanuzel",
                name="Санузел",
                sensors={"temperature": SANUZEL_TEMP, "humidity": SANUZEL_HUMIDITY},
                devices=[
                    DeviceConfig(
                        id=EXHAUST_FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(EXHAUST_PARAMS),
                            )
                        ],
                    )
                ],
            ),
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать конвейер вентиляции из двух комнат.

    Returns:
        Движок, роутер и помнящий команды диспетчер.
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


class TestOutsideSensorFailureIsIsolated:
    """Отказ датчика улицы останавливает только пересчёт скорости (FR-046)."""

    @pytest.mark.asyncio
    async def test_supply_stays_idle_without_outside_temperature(self) -> None:
        """Без улицы рекуператор не выбирает режим и скорость.

        Returns:
            Ничего.
        """
        engine, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=KABINET_TEMP,
            new_state="20.0",
            old_state="19.0",
            context={"is_winter": True},
        )

        assert engine.get_state(SUPPLY_FSM).current_state == "IDLE"  # type: ignore[union-attr]
        assert "set_preset_mode" not in dispatcher.services()
        assert "turn_on" not in dispatcher.services(), (
            f"без улицы ушли команды {dispatcher.services()}: режим и скорость "
            "выбирать не по чему (FR-029)"
        )

    @pytest.mark.asyncio
    async def test_exhaust_still_runs_from_bathroom_heat(self) -> None:
        """Высокая температура санузла включает вытяжку при молчащей улице.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SANUZEL_TEMP,
            new_state="26.0",
            old_state="24.0",
            context={"is_winter": True},
        )

        assert "turn_on" in dispatcher.services(), (
            f"санузел 26 °C, а вытяжка не включилась: {dispatcher.services()} — "
            "отказ датчика улицы не имеет права гасить соседнее решение (FR-046)"
        )
        assert dispatcher.intents[-1].device_id == EXHAUST_FAN, (
            "вытяжка включена не у своего прибора"
        )
        assert not dispatcher.intents[-1].data, (
            f"вытяжка получила данные {dispatcher.intents[-1].data!r}: у неё нет "
            "скорости, и Home Assistant отвергнет команду (FR-028)"
        )

    @pytest.mark.asyncio
    async def test_exhaust_silent_humidity_low_temperature_stays_off(self) -> None:
        """Санузел сух и не перегрет — вытяжка не включается.

        Returns:
            Ничего.
        """
        _, router, dispatcher = _build()

        await router.route_state_change(
            entity_id=SANUZEL_TEMP,
            new_state="23.0",
            old_state="26.0",
            context={"is_winter": True},
        )

        assert "turn_on" not in dispatcher.services(), (
            f"сухой санузел 23 °C, а вытяжка включилась: {dispatcher.services()}"
        )
