"""Подписка ограничивается списком сущностей — на нашей стороне.

Найдено в бою 2026-10-07. Платформа подписана на **все** события
`state_changed` без фильтра, а в доме 1502 синхронизированные сущности против
десяти описанных в манифесте. Каждое изменение состояния любой сущности —
датчика температуры, `sun.sun`, заряда батареи — приходило в платформу и
отбивалось как `unknown_entity`.

Ключевая поправка 2026-10-08. Этот файл раньше утверждал, что WebSocket API
Home Assistant принимает в `subscribe_events` поле `entity_ids`, и проверял,
что список уходит на сервер. Утверждение было неверным — проверено на живом HA
пятью вариантами подписки:

| Кадр подписки                                   | Ответ HA          |
|------------------------------------------------|-------------------|
| `event_type: state_changed`                     | `success: true`   |
| `event_type: state_changed, entity_ids: [...]`  | `invalid_format`  |
| `event_type: state_changed, entity_ids: []`     | `invalid_format`  |
| `event_type: state_changed, entity_id: ...`     | `invalid_format`  |
| без `event_type`                                | `success: true`   |

Ответ на второй кадр: `extra keys not allowed @ data['entity_ids']`.

То есть платформа годами отправляла ключ, который HA не принимает, HA отвергал
подписку целиком, а платформа не читала ответ и писала в журнал «subscribed».
События не приходили никогда — при зелёном `/ready`, потому что соединение живо,
а подписка — это другое. Ни одна проверка не спрашивала HA, принял ли он
подписку: все проверяли, что сообщение ушло.

**Почему фильтр у нас, а не на сервере.** Ограничение на стороне HA
невозможно: такого поля нет. Значит, подписка идёт на все события, а лишние
отбрасываются на входе. Цена — 1500 событий в минуту идут по сети и разбираются,
но не доходят до движка и не пишутся в историю. Обмен сознательный: тишина при
исправном соединении неотличима от поломки, а лишний трафик виден и измерим.

**Что должно остаться как есть.** Пустой список фильтра означает «все
сущности»: пустой манифест должен означать подписку на всё и отсутствие
отбрасывания, а не молчание. Иначе платформа с пустым манифестом выглядела бы
исправной и молчала бы.

Ответ HA на подписку проверяется отдельно, в
`tests/integration/test_subscription_confirmed.py`.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import pytest

from adapters import ha_adapter as ha_adapter_module
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


async def _subscribe(entity_ids: list[str] | None) -> SimpleHAWebSocketClient:
    """Выполнить подписку и вернуть клиента.

    Args:
        entity_ids: Список сущностей для фильтра либо None.

    Returns:
        Клиент, отправивший подписку.
    """
    client = SimpleHAWebSocketClient(url="ws://fake", token="token")
    client.ws = _Socket()
    client.connected = True

    filter_dict: dict[str, Any] = {"type": "state_changed"}
    if entity_ids is not None:
        filter_dict["entity_ids"] = entity_ids

    async def handler(_payload: dict[str, Any]) -> None:
        pass

    await _subscribe_without_answer(client, handler, filter_dict)

    return client


async def _subscribe_without_answer(
    client: SimpleHAWebSocketClient,
    handler: Any,
    filter_dict: dict[str, Any],
) -> None:
    """Подписаться на сокете, который не отвечает.

    Отдельная функция, а не подмена ожидания на месте: замкчатый сокет в этих
    проверках — условие опыта, а не причина спотыкаться о таймаут. Сокращённое
    ожидание здесь честно: настоящий код ждёт
    ``SUBSCRIPTION_TIMEOUT_SEC``, и подменять его на 10 секунд в каждой
    проверке незачем.

    Args:
        client: Клиент с подставным сокетом.
        handler: Обработчик событий.
        filter_dict: Фильтр подписки.

    Returns:
        Ничего.
    """
    with mock.patch.object(ha_adapter_module, "SUBSCRIPTION_TIMEOUT_SEC", 0.01):
        await client.subscribe(handler=handler, filter_dict=filter_dict)


@pytest.mark.asyncio
class TestSubscriptionFrameIsAccepted:
    """Кадр подписки должен приниматься настоящим HA."""

    async def test_unsupported_entity_ids_key_is_not_sent(self) -> None:
        """Ключ `entity_ids` не отправляется: HA его не принимает.

        Returns:
            Ничего.
        """
        client = await _subscribe([ENTITY_KITCHEN, ENTITY_MOTION])

        frame = client.ws.sent[-1]  # type: ignore[union-attr]

        assert "entity_ids" not in frame, (
            f"отправлен ключ `entity_ids`, который Home Assistant отвергает с "
            f"`invalid_format`: {frame}. Подписка не состоится, а платформа "
            f"решит, что подписалась"
        )

    async def test_event_type_is_still_declared(self) -> None:
        """Тип события в кадре остаётся: фильтр сущностей его не заменяет.

        Returns:
            Ничего.
        """
        client = await _subscribe([ENTITY_KITCHEN])

        frame = client.ws.sent[-1]  # type: ignore[union-attr]

        assert frame["type"] == "subscribe_events", frame
        assert frame["event_type"] == "state_changed", frame


@pytest.mark.asyncio
class TestFilterIsRememberedLocally:
    """Список сущностей сохраняется на клиенте и применяется на входе."""

    async def test_entities_are_saved_for_local_filter(self) -> None:
        """Список сущностей сохранён: без него отбрасывать нечего.

        Returns:
            Ничего.
        """
        client = await _subscribe([ENTITY_KITCHEN, ENTITY_MOTION, ENTITY_KITCHEN])

        assert set(client.filtered_entity_ids) == {ENTITY_KITCHEN, ENTITY_MOTION}, (
            f"список сущностей исказился или потерялся: {client.filtered_entity_ids}"
        )

    async def test_empty_list_means_no_filter(self) -> None:
        """Пустой манифест означает подписку на всё, а не молчание.

        Returns:
            Ничего.
        """
        client = await _subscribe([])

        assert client.filtered_entity_ids == (), (
            f"пустой список превратился в фильтр: {client.filtered_entity_ids}. "
            f"Платформа с пустым манифестом станет молчащей: соединение есть, "
            f"/ready зелёный, событий нет"
        )

    async def test_irrelevant_entity_is_dropped_before_handler(self) -> None:
        """Чужая сущность не доходит до обработчика и считается.

        Returns:
            Ничего.
        """
        received: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            received.append(str(payload.get("entity_id")))

        client = SimpleHAWebSocketClient(url="ws://fake", token="token")
        client.ws = _Socket()
        client.connected = True

        await _subscribe_without_answer(
            client,
            handler,
            {"type": "state_changed", "entity_ids": [ENTITY_KITCHEN]},
        )

        await client._deliver({"entity_id": ENTITY_IRRELEVANT, "new_state": "7"})
        await client._deliver({"entity_id": ENTITY_KITCHEN, "new_state": "on"})

        assert received == [ENTITY_KITCHEN], f"до обработчика дошло лишнее: {received}"
        assert client.filtered_out_count == 1, (
            f"отброшенное событие не посчитано: {client.filtered_out_count}. Без "
            f"счётчика «приходят все 1502» снова станет невидимым"
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
