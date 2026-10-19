"""Изменение состояния прибора — повод пересмотреть решение вентиляции.

Боевая находка 2026-10-20: «Приток MAX» у рекуператора держится около пяти
минут, и прибор сам возвращается в «Рекуперацию (лето)». Сторож вентиляции
проверяет решение раз в пять минут и успевает прочитать состояние **до**
отката — команда подтверждения не уходит, и спальня дует обычным режимом на
100 % до следующего тика. Событие самого прибора приходит в момент отката,
поэтому изменение состояния прибора обязано быть таким же поводом, как и
показание датчика.

Проверяется маршрутизатор: изменение состояния вентилятора доходит до его
автомата с последними показаниями комнаты и общими значениями дома; свет и
неизвестные сущности вентиляцию не пересматривают.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.events.event_router import EventRouter
from core.models.manifest import (
    BehaviorConfig,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)


FAN = "fan.spalnia"
LAMP = "light.lamp"
FAN_FSM = "fan.spalnia_ventilation_modes_10"
LAMP_FSM = "light.lamp_lighting_10"


class _Engine:
    """Движок-двойник: помнит, каким автоматам и с каким контекстом пришло событие."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Автоматы устройства.

        Args:
            device_id: Идентификатор устройства.

        Returns:
            Список автоматов устройства.
        """
        return {
            FAN: [FAN_FSM],
            LAMP: [LAMP_FSM],
        }.get(device_id, [])

    def entities_with_trigger(self, trigger: str) -> list[str]:
        """Автоматы, слушающие событие.

        Args:
            trigger: Имя события.

        Returns:
            Оба автомата: так проверяется, что маршрутизатор отбирает именно
            вентиляцию, а не всё, что слушает `settings_changed`.
        """
        del trigger
        return [FAN_FSM, LAMP_FSM]

    def get_state(self, entity_id: str) -> None:
        """Состояние автомата тесту не нужно."""
        return None

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> bool:
        """Запомнить событие.

        Args:
            entity_id: Автомат.
            event: Событие.
            external_ctx: Контекст перехода.
            kwargs: Прочие параметры движка.

        Returns:
            True.
        """
        self.calls.append(
            {"fsm": entity_id, "event": event, "ctx": dict(external_ctx or {}), **kwargs}
        )
        return True


def _router() -> tuple[EventRouter, _Engine]:
    """Маршрутизатор с одной комнатой: вентилятор, лампа и два датчика.

    Returns:
        Маршрутизатор и движок-двойник.
    """
    manifest = Manifest(
        instance=InstanceConfig(id="probe", name="Probe", owner="probe", created_at=""),
        rooms=[
            RoomConfig(
                id="spalnia",
                name="Спальня",
                sensors={
                    "temperature": "sensor.t",
                    "humidity": "sensor.h",
                },
                devices=[
                    DeviceConfig(
                        id=FAN,
                        type="fan",
                        behaviors=[BehaviorConfig(template="ventilation_modes", priority=10)],
                    ),
                    DeviceConfig(
                        id=LAMP,
                        type="light",
                        behaviors=[BehaviorConfig(template="lighting", priority=10)],
                    ),
                ],
            )
        ],
    )
    engine = _Engine()
    return EventRouter(manifest, engine), engine


@pytest.mark.asyncio
async def test_device_change_should_review_ventilation_with_last_measurements() -> None:
    """Откат режима прибора пересматривает вентиляцию с температурой комнаты.

    Returns:
        Ничего.
    """
    router, engine = _router()
    await router.route_state_change("sensor.t", "25.3", "25.0")
    engine.calls.clear()

    await router.route_device_change(
        FAN,
        "on",
        "on",
        {"outside_temperature": 4.5, "is_winter": False},
    )

    assert len(engine.calls) == 1, "изменение прибора не пересмотрело вентиляцию"
    call = engine.calls[0]
    assert call["fsm"] == FAN_FSM
    assert call["event"] == "settings_changed"
    assert call["ctx"]["temperature"] == 25.3, (
        "пересмотр пришёл без показания комнаты: условие «жарко» откажет "
        "guard_data_missing, и «Приток MAX» не вернётся"
    )
    assert call["ctx"]["outside_temperature"] == 4.5
    assert call["ctx"]["entity_id"] == FAN
    assert call["ctx"]["new_state"] == "on"
    assert call["respect_debounce"] is False


@pytest.mark.asyncio
async def test_unknown_entity_change_should_not_touch_ventilation() -> None:
    """Неизвестная сущность не пересматривает вентиляцию.

    Returns:
        Ничего.
    """
    router, engine = _router()

    await router.route_device_change("sensor.unknown", "1", "0")

    assert engine.calls == []


@pytest.mark.asyncio
async def test_light_change_should_not_review_ventilation() -> None:
    """Свет не пересматривает вентиляцию, даже если его автомат слушает настройки.

    Returns:
        Ничего.
    """
    router, engine = _router()

    await router.route_device_change(LAMP, "on", "off")

    assert engine.calls == [], (
        "изменение лампы разослано как пересмотр вентиляции: маршрут прибора "
        "обязан ограничиваться шаблоном вентиляции"
    )
