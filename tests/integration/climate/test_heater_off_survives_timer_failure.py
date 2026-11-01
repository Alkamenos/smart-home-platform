"""Сбой вспомогательного шага не должен отменять выключение обогревателя.

Живая находка 01.11: страховочный таймер сработал, платформа решила выключить
обогреватель, но первый шаг (обнулить таймер прибора) Home Assistant отверг —
и движок пропустил второй шаг, само выключение. Обогреватель остался включённым
на неопределённое время: датчик комнаты к тому моменту молчал, нового решения
не приходило.

Проверяется не действие, а движок: политика «остановиться на первом сбое» верна
для включения (таймер без включённого прибора бессмыслен), но неверна для
выключения — оставить прибор включённым хуже, чем не обнулить таймер.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path
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


TEMPLATE_DIR = Path("src/features")
SETPOINT = 22.0
HYSTERESIS = 0.5
HEATER = "switch.obogrevatel_spalnia"
HEATER_TIMER = "number.obogrevatel_spalnia_countdown"
SENSOR = "sensor.datchik_temperatury_spalnia_temperature"
ROOM = "spalnia"
FSM = "switch.obogrevatel_spalnia_climate_control_10"


class _RejectingDispatcher:
    """Диспетчер, который умеет отказывать выбранному домену."""

    def __init__(self) -> None:
        self.intents: list[Any] = []
        self.reject_domain: str | None = None

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду и решить, доставлена ли она.

        Args:
            intent: Команда от действия шаблона.

        Returns:
            False, если домен команды назван отказывающим.
        """
        self.intents.append(intent)
        return intent.domain != self.reject_domain

    def services(self) -> list[str]:
        """Сервисы всех попыток, включая неудачные.

        Returns:
            Список имён сервисов.
        """
        return [intent.service for intent in self.intents]


def _manifest() -> Manifest:
    """Манифест из одной комнаты: датчик температуры и обогреватель.

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
                name="Спальня",
                sensors={"temperature": SENSOR},
                devices=[
                    DeviceConfig(
                        id=HEATER,
                        type="climate",
                        behaviors=[
                            BehaviorConfig(
                                template="climate_control",
                                priority=10,
                                params={
                                    "hysteresis": HYSTERESIS,
                                    "run_minutes": 15,
                                    "heater_timer": HEATER_TIMER,
                                },
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RejectingDispatcher]:
    """Собрать боевой конвейер климата с управляемым диспетчером.

    Returns:
        Движок, роутер и диспетчер.
    """
    from core.action_handlers import register_all_actions
    from core.guards.builtin import register_all_guards

    registry = Registry()
    register_all_guards(registry, None)
    register_all_actions(registry)
    engine = FSMEngine()
    dispatcher = _RejectingDispatcher()
    engine.set_command_dispatcher(dispatcher)  # type: ignore[arg-type]
    manifest = _manifest()
    FSMFactory(engine=engine, registry=registry, event_bus=None).create_and_register(manifest)
    return engine, EventRouter(manifest, engine), dispatcher


@pytest.mark.asyncio
async def test_failed_timer_zero_does_not_skip_heater_off() -> None:
    """Обнуление таймера не прошло — прибор всё равно выключается.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_state_change(
        entity_id=SENSOR,
        new_state="20.5",
        old_state="22.0",
        context={"climate_setpoint": SETPOINT, "hysteresis": HYSTERESIS, "room": ROOM},
    )
    assert engine.get_state(FSM).current_state == "HEATING", "обогрев не начался"

    dispatcher.intents.clear()
    dispatcher.reject_domain = "number"

    await engine.trigger(FSM, "timeout", respect_debounce=False)

    assert "set_value" in dispatcher.services(), (
        "шаг обнуления таймера даже не был отправлен — тест проверяет не то"
    )
    assert "turn_off" in dispatcher.services(), (
        "после сбоя обнуления таймера выключение прибора пропущено: обогреватель "
        "остаётся включённым, а автомат уже считает себя в IDLE"
    )
    assert engine.get_state(FSM).current_state == "IDLE"


@pytest.mark.asyncio
async def test_required_step_failure_still_stops_the_chain() -> None:
    """Сбой обязательного шага по-прежнему останавливает цепочку.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()
    # Включение прибора — обязательный шаг: таймер без него бессмыслен.
    dispatcher.reject_domain = "switch"

    await router.route_state_change(
        entity_id=SENSOR,
        new_state="20.5",
        old_state="22.0",
        context={"climate_setpoint": SETPOINT, "hysteresis": HYSTERESIS, "room": ROOM},
    )

    assert "turn_on" in dispatcher.services(), "включение даже не пытались отправить"
    assert "set_value" not in dispatcher.services(), (
        "после сбоя обязательного включения платформа продолжила цепочку: таймер "
        "ушёл бы на выключенный прибор, и отказ выглядел бы как успех"
    )
