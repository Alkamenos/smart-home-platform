"""Подписка на события обязана быть настоящей: отказ HA — это отказ.

Что произошло в бою
--------------------

2026-10-08 контейнер отправлял подписку так:

    {"id": 1, "type": "subscribe_events", "event_type": "state_changed",
     "entity_ids": [...21 сущность...]}

Home Assistant отвечал:

    {"id": 1, "type": "result", "success": false,
     "error": {"code": "invalid_format",
               "message": "extra keys not allowed @ data['entity_ids']"}}

Фильтра `entity_ids` в API Home Assistant нет — проверено пятью вариантами
подписки на живом HA: принимаются `event_type` и `event_id`, а `entity_ids` и
даже `entity_id` отвергаются как лишние ключи.

Прежний код отправлял подписку и **не ждал ответа**. Платформа писала в журнал
«subscribed to state_changed for 21 entities» — сообщала об успехе, которого не
было. HA отверг подписку, события не приходили никогда, а `/ready` отвечал
`home_assistant: ok`, потому что соединение живо: подписка и соединение —
разные вещи, и платформа проверяла только второе.

Почему это прожило столько времени
----------------------------------

Тот же класс, что #9, #18 и разрыв WebSocket: механизм есть, выглядит
исправным, данных ему никто не передаёт. Ни одна из прежних проверок не
спрашивала HA, принял ли он подписку, — все проверяли, что сообщение ушло.

Что проверяется
---------------

1. Ответ HA на подписку обязателен и читается.
2. Отказ HA виден: он в состоянии клиента и в причине, а не проглатывается.
3. Неподдерживаемый ключ не отправляется молча.
4. Ограничение по сущностям сохраняется и применяется на нашей стороне.
5. Отброшенные события считаются — иначе «приходят все 1502» снова невидимо.

Проверки идут против поддельного HA, который отвечает отказом так же, как
настоящий.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient


class _RecordingHA:
    """Поддельный HA, который честно отвечает на подписку.

    Args:
        error_code: Код отказа; ``None`` означает успех.
    """

    def __init__(self, error_code: str | None = None) -> None:
        """Создать поддельный сервер.

        Args:
            error_code: Код отказа на подписку либо ``None`` для успеха.
        """
        self.error_code = error_code
        self.server: Any = None
        self.subscription_requests: list[dict[str, Any]] = []

    @property
    def url(self) -> str:
        """Адрес подключения.

        Returns:
            URL с фактическим портом.
        """
        assert self.server is not None, "сервер не поднят"
        port = self.server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/api/websocket"

    async def _handler(self, ws: Any) -> None:
        """Обслужить соединение до разрыва.

        Args:
            ws: Соединение с клиентом.

        Returns:
            Ничего.
        """
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.7"}))
        try:
            async for raw in ws:
                message = json.loads(raw)
                kind = message.get("type")

                if kind == "auth":
                    await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.7"}))
                elif kind == "subscribe_events":
                    self.subscription_requests.append(message)
                    await ws.send(json.dumps(self._result(message)))
                    await asyncio.sleep(0.05)
                    await ws.close(1001, "going away")
                    return
        except Exception:  # noqa: BLE001 — сервер закрывается клиентом
            return

    def _result(self, request: dict[str, Any]) -> dict[str, Any]:
        """Ответить так, как ответил бы настоящий HA.

        Args:
            request: Запрос подписки.

        Returns:
            Ответ с ``success`` и, при отказе, с причиной.
        """
        if self.error_code is None:
            return {"id": request["id"], "type": "result", "success": True, "result": None}
        return {
            "id": request["id"],
            "type": "result",
            "success": False,
            "error": {
                "code": self.error_code,
                "message": f"extra keys not allowed @ data['{self.error_code}']",
            },
        }

    async def start(self) -> None:
        """Поднять сервер.

        Returns:
            Ничего.
        """
        from websockets.asyncio.server import serve

        self.server = await serve(self._handler, "127.0.0.1", 0)

    async def stop(self) -> None:
        """Остановить сервер.

        Returns:
            Ничего.
        """
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


async def _noop_handler(_payload: dict[str, Any]) -> None:
    """Обработчик событий, которому всё равно.

    Args:
        _payload: Событие от HA.

    Returns:
        Ничего.
    """


async def _subscribe(
    error_code: str | None,
    entity_ids: list[str],
) -> tuple[SimpleHAWebSocketClient, _RecordingHA]:
    """Подключиться и подписаться.

    Args:
        error_code: Код отказа поддельного HA либо ``None``.
        entity_ids: Сущности, ради которых подписываемся.

    Returns:
        Клиент и поддельный сервер.
    """
    fake = _RecordingHA(error_code=error_code)
    await fake.start()

    client = SimpleHAWebSocketClient(url=fake.url, token="пробный")
    await client.connect()

    await client.subscribe(_noop_handler, {"type": "state_changed", "entity_ids": entity_ids})
    await asyncio.sleep(0.4)

    return client, fake


async def _teardown(client: SimpleHAWebSocketClient, fake: _RecordingHA) -> None:
    """Закрыть клиента и остановить сервер.

    Args:
        client: Клиент подписки.
        fake: Поддельный сервер.

    Returns:
        Ничего.
    """
    await client.close()
    await fake.stop()


class TestSubscriptionIsConfirmed:
    """Подписка успешна только после ответа HA."""

    @pytest.mark.asyncio
    async def test_rejected_subscription_is_not_successful(self) -> None:
        """Отказ HA виден в состоянии, а не проглочен отправкой.

        Прежде код отправлял подписку и не ждал ответа: журнал писал
        «subscribed», HA отвечал отказом, и события не приходили никогда — при
        зелёном `/ready`.
        """
        client, fake = await _subscribe(error_code="invalid_format", entity_ids=["light.kitchen"])

        try:
            assert fake.subscription_requests, "подписка не отправлена — проверка бессмысленна"
            assert client.subscription_confirmed is False, (
                "HA отверг подписку, а клиент считает её успешной: в журнале "
                "будет написано «subscribed», события не придут никогда"
            )
        finally:
            await _teardown(client, fake)

    @pytest.mark.asyncio
    async def test_rejection_reason_is_kept(self) -> None:
        """Причина отказа сохранена: видно, что именно сказал HA.

        Без неё отказ неотличим от «подписка прошла, событий нет» — а это уже
        неотличимо от поломки доставки, то есть от #9.
        """
        client, fake = await _subscribe(error_code="invalid_format", entity_ids=["light.kitchen"])

        try:
            assert client.subscription_error, (
                "причина отказа HA не сохранена: по журналу отказ подписки неотличим от успеха"
            )
            assert "invalid_format" in client.subscription_error, (
                f"в причине нет кода отказа HA: {client.subscription_error!r}"
            )
        finally:
            await _teardown(client, fake)

    @pytest.mark.asyncio
    async def test_confirmed_subscription_has_no_error(self) -> None:
        """Принятая подписка подтверждена и без ошибки.

        Проверяется отдельно, иначе проверки на отказ проходили бы при любом
        состоянии полей — то есть проверяли бы не то.
        """
        client, fake = await _subscribe(error_code=None, entity_ids=["light.kitchen"])

        try:
            assert client.subscription_confirmed is True, (
                "HA принял подписку, но клиент не считает её подтверждённой"
            )
            assert client.subscription_error is None, (
                f"при принятой подписке записана ошибка: {client.subscription_error!r}"
            )
        finally:
            await _teardown(client, fake)


class TestFilterIsAppliedLocally:
    """Ограничение по сущностям не может исчезнуть вместе с ключом."""

    @pytest.mark.asyncio
    async def test_unsupported_key_is_not_sent(self) -> None:
        """Ключ, который HA не принимает, не отправляется молча.

        Настоящий HA отвечает `extra keys not allowed`. Отправлять такой ключ —
        значит получать отказ и не знать об этом. Фильтр либо применяется у нас,
        либо не отправляется.
        """
        client, fake = await _subscribe(error_code=None, entity_ids=["light.kitchen"])

        try:
            sent = fake.subscription_requests[0]
            assert "entity_ids" not in sent, (
                f"платформа отправила ключ `entity_ids`, который Home Assistant "
                f"не принимает: {sent}. Подписка заведомо отвергается"
            )
        finally:
            await _teardown(client, fake)

    @pytest.mark.asyncio
    async def test_requested_entities_are_remembered(self) -> None:
        """Список сущностей сохранён: отбрасывать лишние нечем без него."""
        client, fake = await _subscribe(error_code=None, entity_ids=["light.kitchen", "light.hall"])

        try:
            assert set(client.filtered_entity_ids) == {"light.kitchen", "light.hall"}, (
                f"список сущностей не сохранён: {client.filtered_entity_ids}"
            )
        finally:
            await _teardown(client, fake)

    @pytest.mark.asyncio
    async def test_foreign_entity_is_dropped(self) -> None:
        """Событие чужой сущности не доходит до обработчика.

        Проверяется поведением: без фильтра на нашей стороне приходят все 1502
        сущности дома, и платформа разбирает каждую — то есть ограничение
        перестало бы существовать вместе с неработающим ключом.
        """
        fake = _RecordingHA(error_code=None)
        await fake.start()

        received: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            received.append(str(payload.get("entity_id")))

        client = SimpleHAWebSocketClient(url=fake.url, token="пробный")
        await client.connect()
        await client.subscribe(handler, {"type": "state_changed", "entity_ids": ["light.kitchen"]})

        try:
            await client._deliver({"entity_id": "light.kitchen", "new_state": "on"})
            await client._deliver({"entity_id": "sensor.foreign_humidity", "new_state": "50"})
            await client._deliver({"entity_id": "light.hall", "new_state": "on"})

            assert received == ["light.kitchen"], (
                f"до обработчика дошли чужие сущности: {received}. Ограничение "
                f"по манифесту не работает"
            )
            assert client.filtered_out_count == 2, (
                f"отброшенные события не посчитаны: {client.filtered_out_count}. "
                f"Без счётчика «приходят все 1502» снова станет невидимым"
            )
        finally:
            await _teardown(client, fake)
