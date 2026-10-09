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

import asyncio
import json
import logging
from typing import Any
from unittest import mock

import pytest

import core.metrics as core_metrics_module
from adapters import ha_adapter as ha_adapter_module
from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient


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


async def _client_with_live_filter(
    snapshot: list[str],
    provider: Any,
    received: list[str],
) -> SimpleHAWebSocketClient:
    """Клиент, подписанный со снимком списка, но с живым провайдером фильтра.

    Ровно то, что ставит адаптер: ``subscribe()`` запоминает снимок на момент
    подписки, а провайдер читает манифест в момент события (Known Issue #83).

    Args:
        snapshot: Список сущностей, переданный в ``subscribe()``.
        provider: Callable, возвращающий актуальный список сущностей.
        received: Список, куда обработчик складывает доставленные entity_id.

    Returns:
        Клиент с установленным провайдером.
    """
    client = SimpleHAWebSocketClient(url="ws://fake", token="token")
    client.ws = _Socket()
    client.connected = True
    client.entity_filter_provider = provider

    async def handler(payload: dict[str, Any]) -> None:
        received.append(str(payload.get("entity_id")))

    await _subscribe_without_answer(
        client,
        handler,
        {"type": "state_changed", "entity_ids": snapshot},
    )

    return client


@pytest.mark.asyncio
class TestFilterFollowsManifestLive:
    """Фильтр читает манифест в момент события, а не снимок при подписке.

    Known Issue #83: устройство, добавленное после старта, не получало
    собственных событий до рестарта — ``filtered_entity_ids`` замораживался
    в ``subscribe()``. Список обязан перечитываться у источника (манифест
    адаптера) на каждом событии; переподписка не нужна, HA и так шлёт все
    события, фильтр чисто локальный.
    """

    async def test_entity_added_after_subscribe_is_accepted(self) -> None:
        """Сущность, добавленная после подписки, события свои получает.

        Returns:
            Ничего.
        """
        entities = [ENTITY_KITCHEN]
        received: list[str] = []
        client = await _client_with_live_filter([ENTITY_KITCHEN], lambda: list(entities), received)

        # Манифест изменился после подписки: комната получила датчик движения.
        entities = [ENTITY_KITCHEN, ENTITY_MOTION]

        await client._deliver({"entity_id": ENTITY_MOTION, "new_state": "on"})

        assert received == [ENTITY_MOTION], (
            f"событие сущности, добавленной после старта, отброшено: {received}. "
            f"Фильтр использовал снимок из subscribe() вместо актуального "
            f"манифеста (Known Issue #83): до рестарта платформа слепа по нему"
        )

    async def test_entity_removed_from_manifest_is_dropped(self) -> None:
        """Сущность, убранная из манифеста, перестаёт проходить фильтр.

        Returns:
            Ничего.
        """
        entities = [ENTITY_KITCHEN, ENTITY_MOTION]
        received: list[str] = []
        client = await _client_with_live_filter(
            [ENTITY_KITCHEN, ENTITY_MOTION], lambda: list(entities), received
        )

        entities = [ENTITY_KITCHEN]

        await client._deliver({"entity_id": ENTITY_MOTION, "new_state": "on"})

        assert received == [], (
            f"до обработчика дошло событие сущности, которой больше нет в "
            f"манифесте: {received}. Живой провайдер игнорируется"
        )
        assert client.filtered_out_count == 1

    async def test_empty_live_list_means_no_filter(self) -> None:
        """Пустой манифест в момент события означает «фильтр выключен».

        Та же семантика, что и у снимка: платформа с пустым манифестом должна
        получать всё и отбивать у себя, а не молчать при зелёном /ready.

        Returns:
            Ничего.
        """
        entities = [ENTITY_KITCHEN]
        received: list[str] = []
        client = await _client_with_live_filter([ENTITY_KITCHEN], lambda: list(entities), received)

        entities = []

        await client._deliver({"entity_id": ENTITY_IRRELEVANT, "new_state": "7"})

        assert received == [ENTITY_IRRELEVANT], (
            f"пустой живой список не выключил фильтр: {received}"
        )

    async def test_frozen_snapshot_filters_when_no_provider(self) -> None:
        """Без провайдера фильтр остаётся на снимке подписки (обратная связь).

        Returns:
            Ничего.
        """
        received: list[str] = []
        client = SimpleHAWebSocketClient(url="ws://fake", token="token")
        client.ws = _Socket()
        client.connected = True

        async def handler(payload: dict[str, Any]) -> None:
            received.append(str(payload.get("entity_id")))

        await _subscribe_without_answer(
            client,
            handler,
            {"type": "state_changed", "entity_ids": [ENTITY_KITCHEN]},
        )

        await client._deliver({"entity_id": ENTITY_IRRELEVANT, "new_state": "7"})
        await client._deliver({"entity_id": ENTITY_KITCHEN, "new_state": "on"})

        assert received == [ENTITY_KITCHEN], (
            f"снимок без провайдера перестал фильтровать: {received}"
        )

    async def test_filter_size_change_is_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        """Изменение размера фильтра видно в журнале, а не только в коде.

        Returns:
            Ничего.
        """
        entities = [ENTITY_KITCHEN]
        received: list[str] = []
        client = await _client_with_live_filter([ENTITY_KITCHEN], lambda: list(entities), received)

        entities = [ENTITY_KITCHEN, ENTITY_MOTION]

        with caplog.at_level(logging.WARNING, logger="adapters.ha_adapter"):
            await client._deliver({"entity_id": ENTITY_KITCHEN, "new_state": "on"})
            await client._deliver({"entity_id": ENTITY_MOTION, "new_state": "on"})

        records = [
            r.getMessage()
            for r in caplog.records
            if "subscription filter changed" in r.getMessage()
        ]
        assert len(records) == 1, (
            f"изменение фильтра не зафиксировано в журнале (нужен ровно один "
            f"WARNING на изменение): {records}"
        )
        assert "1 -> 2" in records[0], records[0]

    async def test_filtered_event_increments_metric(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Отброшенное событие попадает в /metrics, а не только в память.

        Returns:
            Ничего.
        """
        calls: list[int] = []
        collector = type("Collector", (), {})()
        collector.record_websocket_filtered_event = lambda: calls.append(1)  # type: ignore[attr-defined]
        monkeypatch.setattr(core_metrics_module, "get_metrics_collector", lambda: collector)

        client = await _subscribe([ENTITY_KITCHEN])

        await client._deliver({"entity_id": ENTITY_IRRELEVANT, "new_state": "7"})
        await client._deliver({"entity_id": ENTITY_KITCHEN, "new_state": "on"})

        assert calls == [1], (
            f"счётчик websocket_filtered_events_total увеличен {len(calls)} раз "
            f"(ожидался ровно один — на отброшенное событие)"
        )


@pytest.mark.asyncio
class TestAdapterWiresLiveFilter:
    """Адаптер ставит провайдер на клиента до подписки."""

    async def test_provider_is_set_before_subscribe_and_reads_manifest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Провайдер установлен на момент подписки и отражает изменения манифеста.

        Returns:
            Ничего.
        """

        class _Device:
            def __init__(self, device_id: str) -> None:
                self.id = device_id

        class _Room:
            def __init__(self, devices: list[str]) -> None:
                self.sensors: dict[str, str] = {}
                self.devices = [_Device(d) for d in devices]

        class _Manifest:
            def __init__(self, devices: list[str]) -> None:
                self.rooms = [_Room(devices)]

        manifest = _Manifest([ENTITY_KITCHEN])
        received_provider: list[Any] = []

        class _RecordingWSClient:
            """Клиент, запоминающий провайдер фильтра на момент подписки."""

            def __init__(
                self,
                url: str | None = None,
                token: str | None = None,
                session: Any = None,
            ) -> None:
                self.url = url
                self.token = token
                self.session = session
                self.connected = False
                self.subscription_confirmed = True
                self.subscription_error = None
                self.entity_filter_provider: Any = None
                self._listen_task: asyncio.Task[None] | None = None

            async def connect(self) -> bool:
                self.connected = True
                return True

            async def subscribe(self, callback: Any, filter_dict: Any = None) -> None:
                received_provider.append(self.entity_filter_provider)
                # Выход из цикла переподключения сразу после подписки.
                adapter._shutdown_event.set()

            async def close(self) -> None:
                self.connected = False

        instance = HAAdapter.__new__(HAAdapter)
        instance._mode = "websocket"
        instance._ws_url = "ws://127.0.0.1:1/api/websocket"
        instance._token = "token"
        instance._shutdown_event = asyncio.Event()
        instance._reconnect_task = None
        instance._reconnect_attempt = 0
        instance._connected_once = False
        instance._ws_client = None
        instance._session = None
        instance._last_event_time = 0.0
        instance._message_id = 0
        instance._handlers = {}
        instance._manifest = manifest
        # Колбэки смены суток: адаптер создан в обход __init__, поэтому поля
        # проставляются вручную, как и остальные.
        instance.on_sunset = None
        instance.on_sunrise = None
        adapter = instance

        monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _RecordingWSClient)

        async def _fake_loop(self: Any) -> None:
            await asyncio.sleep(3600)

        monkeypatch.setattr(HAAdapter, "_heartbeat_loop", _fake_loop, raising=True)

        await asyncio.wait_for(adapter._connect_websocket(), timeout=5)

        assert received_provider and received_provider[0] is not None, (
            "entity_filter_provider не установлен к моменту subscribe(): "
            "фильтр останется замороженным снимком, и устройство, добавленное "
            "после старта, не получит собственных событий до рестарта "
            "(Known Issue #83)"
        )

        provider = received_provider[0]
        assert set(provider()) == {ENTITY_KITCHEN}

        manifest.rooms[0].devices.append(_Device(ENTITY_MOTION))

        assert ENTITY_MOTION in provider(), (
            "провайдер не перечитал манифест после изменения: он возвращает "
            "снимок, а не актуальный список"
        )
