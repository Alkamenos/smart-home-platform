"""Событие доставляется только автоматам, которые его слушают (FR-032).

Боевой дефект 2026-10-10: в комнате с датчиком движения и датчиком температуры
роутер отправлял оба события каждому автомату комнаты. Автомат климата получал
`motion_detected`, которого в шаблоне нет, и отвечал `no_transition` — в журнале
это выглядело как «свет отказал включиться», хотя климат и свет живут в одной
комнате и должны получать разные события.

Молчание здесь не вариант: отказ без причины — дефект по FR-032, и разбирать
утренний журнал приходится среди таких записей.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any


class _StubEngine:
    """Движок, у которого один автомат слушает температуру, другой — движение."""

    def __init__(self, listeners: dict[str, set[str]]) -> None:
        self._listeners = listeners
        self.entities = ["fsm_temp", "fsm_motion"]

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы устройства.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            Список идентификаторов автоматов.
        """
        del device_id
        return list(self.entities)

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Автоматы, у которых есть переход на событие.

        Args:
            trigger: Имя события.

        Returns:
            Список автоматов, слушающих событие.
        """
        return list(self._listeners.get(trigger, set()))


def test_motion_event_skips_climate_automaton() -> None:
    """Движение не доставляется автомату климата.

    Returns:
        Ничего.
    """
    from core.events.event_router import EventRouter
    from core.models.manifest import (
        DeviceConfig,
        InstanceConfig,
        Manifest,
        RoomConfig,
    )

    manifest = Manifest(
        version=1,
        instance=InstanceConfig(id="p", name="P", owner="p", created_at=""),
        rooms=[
            RoomConfig(
                id="gostinaia",
                name="Гостиная",
                sensors={
                    "motion": "binary_sensor.dvizheniia",
                    "temperature": "sensor.temperatura",
                },
                devices=[
                    DeviceConfig(id="switch.obogrevatel", type="climate", name="Обогреватель"),
                ],
            )
        ],
    )
    engine = _StubEngine({"temperature_changed": {"fsm_temp"}, "motion_detected": {"fsm_motion"}})

    router = EventRouter(manifest, engine)  # type: ignore[arg-type]
    mapped = {
        fsm_id
        for sensor, entries in router._sensor_to_fsms.items()  # noqa: SLF001
        for fsm_id, _event in entries
    }

    assert "fsm_motion" in mapped, "автомат движения должен получать движение"
    assert "fsm_temp" in mapped, "автомат климата должен получать температуру"


def test_no_transition_noise_is_impossible() -> None:
    """Автомат, не слушающий событие, не получает его вовсе.

    Returns:
        Ничего.
    """
    from core.events.event_router import EventRouter
    from core.models.manifest import (
        DeviceConfig,
        InstanceConfig,
        Manifest,
        RoomConfig,
    )

    manifest = Manifest(
        version=1,
        instance=InstanceConfig(id="p", name="P", owner="p", created_at=""),
        rooms=[
            RoomConfig(
                id="gostinaia",
                name="Гостиная",
                sensors={"motion": "binary_sensor.dvizheniia"},
                devices=[DeviceConfig(id="switch.obogrevatel", type="climate", name="О")],
            )
        ],
    )
    # Ни один автомат не слушает движение
    engine = _StubEngine({"temperature_changed": {"fsm_temp"}})

    router = EventRouter(manifest, engine)  # type: ignore[arg-type]
    entries: list[Any] = [
        (sensor, fsm_id, event)
        for sensor, pairs in router._sensor_to_fsms.items()  # noqa: SLF001
        for fsm_id, event in pairs
    ]

    assert entries == [], f"событие без слушателей доставлять незачем: {entries}"
