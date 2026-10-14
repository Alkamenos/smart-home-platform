"""Сверка состояний устройств с Home Assistant после запуска (B62).

Платформа восстанавливала состояния из `devices.json`, где у штор лежало
5 октября, и показывала вчерашний день: шторы меняются раз в сутки, поэтому
расхождение жило целыми днями (боевая проверка 2026-10-14: «закрытыми»
считались три шторы, а физически закрыта одна).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import pytest

from core.events.event_bus import EventBus
from core.models.device import Device
from services.device_service import DeviceService
from services.device_state_refresh import DeviceStateRefresher


def make_service() -> DeviceService:
    """Сервис устройств с настоящей шиной и без хранилища.

    Returns:
        Сервис устройств.
    """
    return DeviceService(event_bus=EventBus())


def add_device(service: DeviceService, entity_id: str, state: str) -> Device:
    """Положить устройство в сервис так же, как это делает гидратация.

    Args:
        service: Сервис устройств.
        entity_id: Сущность Home Assistant.
        state: Текущее состояние устройства.

    Returns:
        Добавленное устройство.
    """
    device = Device(
        ha_entity_id=entity_id,
        source_id=uuid4(),
        name=entity_id,
        device_type=entity_id.split(".", 1)[0],
        state={"state": state},
    )
    service._devices[device.id] = device
    service._index.add_device(device)
    return device


@dataclass
class FakeAdapter:
    """Внешняя система, отдающая состояния списком.

    Attributes:
        states: Очередь ответов; последний повторяется.
        calls: Сколько раз спросили.
    """

    states: list[list[dict[str, Any]]] = field(default_factory=list)
    calls: int = 0

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояния из очереди."""
        self.calls += 1
        if not self.states:
            return []
        index = min(self.calls - 1, len(self.states) - 1)
        return self.states[index]


@pytest.mark.asyncio
async def test_apply_source_states_updates_known_device() -> None:
    """Состояние известного устройства берётся у источника."""
    service = make_service()
    device = add_device(service, "cover.shtora_v_kabinete", "closed")

    updated = await service.apply_source_states(
        [
            {
                "entity_id": "cover.shtora_v_kabinete",
                "state": "open",
                "attributes": {"current_position": 100},
            }
        ]
    )

    assert updated == 1
    assert device.state["state"] == "open"
    assert device.state["current_position"] == 100


@pytest.mark.asyncio
async def test_apply_source_states_ignores_unknown_entities() -> None:
    """Неизвестные сущности не заводят устройств и не считаются обновлением."""
    service = make_service()
    add_device(service, "cover.shtora_v_kabinete", "closed")

    updated = await service.apply_source_states(
        [{"entity_id": "sensor.something_else", "state": "on", "attributes": {}}]
    )

    assert updated == 0
    assert len(service._devices) == 1


@pytest.mark.asyncio
async def test_apply_source_states_returns_device_to_available() -> None:
    """Ответивший прибор перестаёт считаться недоступным."""
    service = make_service()
    device = add_device(service, "light.svet_nad_stolom", "off")
    device.status = "unavailable"

    await service.apply_source_states(
        [{"entity_id": "light.svet_nad_stolom", "state": "on", "attributes": {}}]
    )

    assert device.status == "available"


@pytest.mark.asyncio
async def test_apply_source_states_counts_only_changes() -> None:
    """Совпавшее состояние обновлением не считается."""
    service = make_service()
    add_device(service, "cover.shtora_v_kabinete", "closed")

    updated = await service.apply_source_states(
        [{"entity_id": "cover.shtora_v_kabinete", "state": "closed", "attributes": {}}]
    )

    assert updated == 0


@pytest.mark.asyncio
async def test_refresher_returns_none_without_states() -> None:
    """Молчание источника — повод повторить, а не «ничего не изменилось»."""
    refresher = DeviceStateRefresher(make_service(), FakeAdapter())

    assert await refresher.run_once() is None


@pytest.mark.asyncio
async def test_refresher_applies_states() -> None:
    """Ответивший источник применяется к устройствам."""
    service = make_service()
    add_device(service, "cover.shtora_v_kabinete", "closed")
    adapter = FakeAdapter(
        [[{"entity_id": "cover.shtora_v_kabinete", "state": "open", "attributes": {}}]]
    )

    assert await DeviceStateRefresher(service, adapter).run_once() == 1


@pytest.mark.asyncio
async def test_refresher_retries_until_source_answers() -> None:
    """Пока связи нет, сверка повторяется и не считается ошибкой."""
    service = make_service()
    add_device(service, "cover.shtora_v_kabinete", "closed")
    adapter = FakeAdapter(
        [
            [],
            [],
            [{"entity_id": "cover.shtora_v_kabinete", "state": "open", "attributes": {}}],
        ]
    )
    refresher = DeviceStateRefresher(service, adapter, interval_sec=0, attempts=5)

    await refresher._run()

    assert adapter.calls == 3
    assert service._devices[next(iter(service._devices))].state["state"] == "open"


@pytest.mark.asyncio
async def test_refresher_without_bulk_reader_does_nothing() -> None:
    """Адаптер без чтения состояний списком сверку не запускает."""
    refresher = DeviceStateRefresher(make_service(), object())

    assert await refresher.run_once() is None


def test_start_without_event_loop_is_not_an_error() -> None:
    """Вне цикла событий сверка не запускается и не падает."""
    refresher = DeviceStateRefresher(make_service(), FakeAdapter())

    assert refresher.start() is False
