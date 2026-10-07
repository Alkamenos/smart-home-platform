"""Подписка должна запрашивать у Home Assistant только нужные сущности.

Найдено в бою 2026-10-07. Платформа подписана на **все** события
`state_changed` без фильтра, а в доме 1502 синхронизированные сущности против 6
описанных в манифесте. Каждое изменение состояния любой сущности — датчика
температуры, `sun.sun`, заряда батареи — приходило в платформу и отбивалось
как `unknown_entity`.

**Почему подписка, а не фильтр в движке.** Движок уже отбивает лишнее, и отказ
теперь молчит после первого упоминания сущности. Но лишнее продолжает
приходить: по сети, по разбору, по вызову `_handle_ws_state_change` на каждое
событие, по записи в `history.db` и публикации `fsm.rejected`. Считать 1500
событий в минуту ради шести нужных — работа впустую, и она растёт вместе с домом.

**Как это лечится.** WebSocket API Home Assistant принимает в
`subscribe_events` поле `entity_ids`: если оно задано, сервер присылает только
эти сущности. Список строится из манифеста — устройства комнат и их датчики, то
есть ровно то, на что платформа подписана по смыслу.

**Что должно остаться как есть.** Пустой список фильтра означает «все сущности»
в API HA, поэтому пустой манифест должен означать подписку на всё, а не на
ничего: иначе платформа с пустым манифестом выглядела бы исправной и молчала
бы. Это не проверка «как лучше», а проверка на молчание.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient


ENTITY_KITCHEN = "light.kitchen"
ENTITY_MOTION = "binary_sensor.kitchen_motion"
ENTITY_IRRELEVANT = "sensor.temperature_humidity_sensor_7c65_temperature"


class _Socket:
    """Сокет, запоминающий отправленные кадры."""

    def __init__(self) -> None:
        """Создать сокет.

        Returns:
            Ничего.
        """
        self.sent: list[dict[str, Any]] = []

    async def send(self, payload: str) -> None:
        """Запомнить отправленный кадр.

        Args:
            payload: JSON-строка кадра.

        Returns:
            Ничего.
        """
        self.sent.append(json.loads(payload))


async def _subscribe(entity_ids: list[str] | None) -> dict[str, Any]:
    """Выполнить подписку и вернуть отправленный кадр.

    Args:
        entity_ids: Список сущностей для фильтра либо None.

    Returns:
        Кадр подписки, отправленный в сокет.
    """
    client = SimpleHAWebSocketClient(url="ws://fake", token="token")
    client.ws = _Socket()
    client.connected = True

    filter_dict: dict[str, Any] = {"type": "state_changed"}
    if entity_ids is not None:
        filter_dict["entity_ids"] = entity_ids

    await client.subscribe(handler=lambda payload: None, filter_dict=filter_dict)
    return client.ws.sent[-1]  # type: ignore[union-attr]


@pytest.mark.asyncio
class TestSubscriptionIsFiltered:
    """Подписка ограничивается списком сущностей."""

    async def test_entity_ids_are_sent_to_home_assistant(self) -> None:
        """Список сущностей уходит в кадре подписки.

        Returns:
            Ничего.
        """
        frame = await _subscribe([ENTITY_KITCHEN, ENTITY_MOTION])

        assert frame["entity_ids"] == [ENTITY_KITCHEN, ENTITY_MOTION], (
            f"список сущностей не отправлен: {frame}. Без него Home Assistant "
            f"присылает все 1502 сущности дома, и платформа отбивает каждое "
            f"событие как `unknown_entity`"
        )

    async def test_event_type_is_still_declared(self) -> None:
        """Тип события в кадре остаётся: фильтр сущностей его не заменяет.

        Returns:
            Ничего.
        """
        frame = await _subscribe([ENTITY_KITCHEN])

        assert frame["type"] == "subscribe_events", frame
        assert frame["event_type"] == "state_changed", frame

    async def test_empty_list_is_not_sent_as_empty(self) -> None:
        """Пустой манифест означает подписку на всё, а не на ничего.

        Returns:
            Ничего.
        """
        frame = await _subscribe([])

        # В API Home Assistant `entity_ids: []` означает «все сущности», то есть
        # пустой список можно отправлять. Но полагаться на это нельзя: пустой
        # список в подписке — это молчание платформы при исправном соединении,
        # а выглядит оно как «событий не приходит».
        assert "entity_ids" not in frame, (
            f"отправлен пустой список сущностей: {frame}. Платформа с пустым "
            f"манифестом станет молчащей: соединение есть, /ready зелёный, "
            f"событий нет. Лучше подписаться на всё и отбивать лишнее, чем не "
            f"получать ничего"
        )

    async def test_entities_are_not_deduplicated_into_garbage(self) -> None:
        """Список сущностей доходит до сервера как есть, без потерь.

        Returns:
            Ничего.
        """
        entities = [ENTITY_KITCHEN, ENTITY_MOTION, ENTITY_KITCHEN]

        frame = await _subscribe(entities)

        assert set(frame["entity_ids"]) == {ENTITY_KITCHEN, ENTITY_MOTION}, (
            f"список сущностей исказился: {frame['entity_ids']}"
        )


@pytest.mark.asyncio
class TestEntityListFromManifest:
    """Список сущностей строится из манифеста."""

    async def test_manifest_entities_are_collected(self) -> None:
        """Устройства комнат и их датчики попадают в список.

        Returns:
            Ничего.
        """
        from core.events.event_router import collect_subscribed_entities

        class _Device:
            def __init__(self, device_id: str) -> None:
                self.id = device_id

        class _Room:
            def __init__(self, sensors: dict[str, str], devices: list[str]) -> None:
                self.sensors = sensors
                self.devices = [_Device(d) for d in devices]

        class _Manifest:
            rooms = [
                _Room({"motion": ENTITY_MOTION}, [ENTITY_KITCHEN]),
                _Room({"temperature": "sensor.temp"}, ["light.bedroom"]),
            ]

        entities = collect_subscribed_entities(_Manifest())

        assert set(entities) == {
            ENTITY_KITCHEN,
            ENTITY_MOTION,
            "light.bedroom",
            "sensor.temp",
        }, f"список сущностей из манифеста неполон: {entities}"

    async def test_empty_manifest_yields_empty_list(self) -> None:
        """Пустой манифест даёт пустой список, а не выдуманные сущности.

        Returns:
            Ничего.
        """
        from core.events.event_router import collect_subscribed_entities

        class _Manifest:
            rooms: list[Any] = []

        assert collect_subscribed_entities(_Manifest()) == []

    async def test_room_without_devices_still_yields_sensors(self) -> None:
        """Датчик комнаты без устройств в список попадает.

        Returns:
            Ничего.
        """
        from core.events.event_router import collect_subscribed_entities

        class _Room:
            sensors = {"motion": ENTITY_MOTION}
            devices: list[Any] = []

        class _Manifest:
            rooms = [_Room()]

        entities = collect_subscribed_entities(_Manifest())

        assert entities == [ENTITY_MOTION], (
            f"датчик комнаты без устройств потерян: {entities}. По нему приходят "
            f"события движения, и без него автоматика молчала бы"
        )
