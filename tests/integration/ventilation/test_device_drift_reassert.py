"""Откат «Притока MAX» прибором возвращается сразу, а не через пять минут.

Боевая находка 2026-10-20 (спальня): платформа решила «жарко» и поставила
«Приток MAX», прибор через пять минут сам вернулся в «Рекуперацию (лето)» с
прежними 100 %, а сторож в этот же миг прочитал состояние **до** отката и
пропустил подтверждение. Спальня дула обычным режимом на 100 % ещё пять минут.

Проверка идёт на настоящих объектах: движок, роутер, фабрика и шаблон. Событие
прибора обязано пересмотреть решение и вернуть «Приток MAX» немедленно.

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


SENSOR = "sensor.datchik_temperatury_spalnia_temperature"
FAN = "fan.base_smart"
ROOM = "spalnia"
PRIORITY = 10
FAN_FSM = f"{FAN}_ventilation_modes_{PRIORITY}"

PARAMS: dict[str, Any] = {
    "ventilation_role": "supply",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 42,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
    "airing_seconds": 3600,
}

HOT = {
    "outside_temperature": 4.5,
    "is_winter": False,
    "comfort_max": 22.0,
    "climate_setpoint": 20.0,
    "ventilation_on": True,
}


class _RecordingDispatcher:
    """Диспетчер, помнящий команды вместо отправки в Home Assistant."""

    def __init__(self) -> None:
        self.intents: list[Any] = []

    async def submit(self, intent: Any) -> bool:
        """Запомнить команду.

        Args:
            intent: Команда действия.

        Returns:
            True.
        """
        self.intents.append(intent)
        return True

    def presets(self) -> list[Any]:
        """Запрошенные режимы рекуператора.

        Returns:
            Список значений `preset_mode`.
        """
        return [i.data.get("preset_mode") for i in self.intents if i.service == "set_preset_mode"]


def _manifest() -> Manifest:
    """Манифест из одной спальни с рекуператором.

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
                        id=FAN,
                        type="fan",
                        behaviors=[
                            BehaviorConfig(
                                template="ventilation_modes",
                                priority=PRIORITY,
                                params=dict(PARAMS),
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(global_manual_lockout_min=60),
    )


def _build() -> tuple[FSMEngine, EventRouter, _RecordingDispatcher]:
    """Собрать конвейер: движок, роутер и помнящий команды диспетчер.

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
        engine: Движок.
        fsm: Идентификатор автомата.

    Returns:
        Имя состояния.
    """
    state = engine.get_state(fsm)
    assert state is not None
    return state.current_state


@pytest.mark.asyncio
async def test_device_drift_should_reassert_airing_immediately() -> None:
    """Прибор снял «Приток MAX» — платформа возвращает его сразу.

    Returns:
        Ничего.
    """
    engine, router, dispatcher = _build()

    await router.route_state_change(
        entity_id=SENSOR, new_state="25.4", old_state="25.2", context=dict(HOT)
    )
    assert _state(engine, FAN_FSM) == "AIRING", "жара в комнате не включила «Приток MAX»"
    dispatcher.intents.clear()

    await router.route_device_change(FAN, "on", "on", dict(HOT))

    assert _state(engine, FAN_FSM) == "AIRING", (
        "изменение прибора увело автомат из «Притока MAX»: решение о жаре не изменилось"
    )
    assert dispatcher.presets() == ["Приток MAX"], (
        "откат режима прибором не вернул «Приток MAX»: спальня осталась бы на "
        "«Рекуперации (лето)» на 100 % до следующего тика сторожа"
    )
