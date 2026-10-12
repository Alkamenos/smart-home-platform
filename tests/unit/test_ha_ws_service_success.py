"""Отказ сервиса Home Assistant не выглядит успехом (боевой разбор 2026-10-12).

Спека 014, B41/D23. Home Assistant отвечает на вызов сервиса сообщением с
``success``: при отказе (например, лишний ключ в данных команды) — ``false``.
Клиент раньше смотрел только на ``result`` и не замечал отказ, поэтому адаптер
печатал «выполнен», а цепочка «решение → команда → прибор» считалась исправной,
хотя команду отбило. Здесь проверяется, что отказ поднимается исключением.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient


class _FakeWS:
    """WebSocket, отвечающий заранее заданным сообщением.

    ``send`` вызывается внутри ``call_service`` до ожидания ответа, поэтому
    обработчик по ``id`` уже зарегистрирован — остаётся отдать ему кадр.
    """

    def __init__(self, client: SimpleHAWebSocketClient, response: dict[str, Any]) -> None:
        self._client = client
        self._response = response

    async def send(self, raw: str) -> None:
        """Отдать обработчику ответ, как это сделал бы Home Assistant.

        Args:
            raw: Сериализованный кадр запроса (в нём есть ``id``).
        """
        msg_id = json.loads(raw)["id"]
        handler = self._client._handlers.get(msg_id)
        assert handler is not None, "обработчик ответа не зарегистрирован"
        handler({"id": msg_id, **self._response})


def _client(response: dict[str, Any]) -> SimpleHAWebSocketClient:
    """Клиент с подключённым «WebSocket», отдающим заданный ответ.

    Args:
        response: Тело ответа Home Assistant.

    Returns:
        Настроенный клиент.
    """
    client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="t")
    client.connected = True
    client.ws = _FakeWS(client, response)  # type: ignore[assignment]
    return client


class TestServiceErrorsAreVisible:
    """Ошибку сервиса видно, а не «выполнено»."""

    @pytest.mark.asyncio
    async def test_failure_raises(self) -> None:
        """``success: false`` поднимает исключение, а не тихо возвращается.

        Returns:
            Ничего.
        """
        client = _client({"success": False, "error": {"code": "invalid_format", "message": "bad"}})

        with pytest.raises(RuntimeError, match="failed"):
            await client.call_service(
                domain="fan", service="set_preset_mode", service_data={"preset_mode": "x"}
            )

    @pytest.mark.asyncio
    async def test_success_returns_result(self) -> None:
        """Успешный вызов возвращает ``result`` как прежде.

        Returns:
            Ничего.
        """
        client = _client({"success": True, "result": {"context": {"id": "abc"}}})

        result = await client.call_service(
            domain="fan", service="turn_on", service_data={"percentage": 42}
        )

        assert result == {"context": {"id": "abc"}}

    @pytest.mark.asyncio
    async def test_response_without_success_flag_is_tolerated(self) -> None:
        """Ответ без поля ``success`` не считается отказом (обратная совместимость).

        Returns:
            Ничего.
        """
        client = _client({"result": None})

        assert await client.call_service(domain="fan", service="turn_off", service_data={}) is None
