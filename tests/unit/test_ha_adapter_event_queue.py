"""Команда, отправленная из обработчика события, не должна ждать саму себя.

Проверено на живом HA 2026-10-08. Событие приходит в цикл чтения сокета,
обработчик события отправляет команду автоматики и ждёт ответа Home
Assistant. Ответ читает **тот же** цикл: чтение заблокировано до конца
обработки, обработка — до таймаута ответа. Итог: каждая команда стоила ровно
15 секунд, а `context.id`, по которому своё действие отличается от действия
человека, терялся — и платформа засчитывала собственные команды как ручные,
включая блокировку против себя.

Проверка поднимает настоящий цикл чтения на заглушке сокета и требует, чтобы
команда из обработчика вернула ответ **быстро и с контекстом**. Ветка без
очередиevents упирается в таймаут и падает по времени, а не по смыслу, поэтому
время здесь и есть проверка.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient


#: Ответ Home Assistant на вызов сервиса: контекст, по которому платформа
#: узнаёт своё собственное действие.
SERVICE_RESULT = {"context": {"id": "ctx-own-1", "parent_id": None, "user_id": "u-1"}}

#: Сколько команда может ждать ответ. Настоящий таймаут клиента — 15 с, и при
#: взаимоблокировке проверка ждала бы именно его; 2 с отделяет «ответ пришёл»
#: от «ответ не придёт никогда».
COMMAND_TIMEOUT_SEC = 2.0


class _SoketSlojnyj:
    """Заглушка сокета: отвечает на `call_service` контекстом.

    Имя класса латиницей с русским суффиксом выглядит нелепо, но класс —
    честная замена сокету с тем же контрактом, что требует клиент.
    """

    def __init__(self) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []

    def __aiter__(self) -> _SoketSlojnyj:
        return self

    async def __anext__(self) -> str:
        return await self.incoming.get()

    async def send(self, raw: str) -> None:
        """Отправить сообщение и ответить на вызов сервиса.

        Args:
            raw: Сообщение клиента в виде JSON-строки.

        Returns:
            Ничего.
        """
        message = json.loads(raw)
        self.sent.append(message)
        if message.get("type") == "call_service":
            await self.incoming.put(
                json.dumps(
                    {
                        "id": message["id"],
                        "type": "result",
                        "success": True,
                        "result": SERVICE_RESULT,
                    }
                )
            )


async def _клиент() -> tuple[SimpleHAWebSocketClient, _SoketSlojnyj]:
    """Клиент с работающим циклом чтения на заглушке сокета.

    Returns:
        Клиент и заглушка сокета.
    """
    soket = _SoketSlojnyj()
    client = SimpleHAWebSocketClient(url="ws://localhost:8123", token="token")
    client.ws = soket
    client.connected = True
    client._listen_task = asyncio.create_task(client._listen_loop())
    client._event_worker_task = asyncio.create_task(client._event_worker())
    return client, soket


class TestCommandFromEventHandler:
    """Ответ на команду приходит, хотя она отправлена из обработчика события."""

    @pytest.mark.asyncio
    async def test_service_call_from_handler_gets_its_context(self) -> None:
        """Обработчик события шлёт команду и получает контекст ответа."""
        client, soket = await _клиент()
        получено: dict[str, Any] = {}

        async def handler(payload: dict[str, Any]) -> None:
            получено["результат"] = await client.call_service(
                domain="light",
                service="turn_on",
                service_data={"entity_id": "light.probe"},
                return_response=True,
            )

        client._event_handler = handler
        try:
            await soket.incoming.put(
                json.dumps(
                    {
                        "type": "event",
                        "event": {
                            "event_type": "state_changed",
                            "data": {"entity_id": "light.probe"},
                        },
                    }
                )
            )
            for _ in range(200):
                if "результат" in получено:
                    break
                await asyncio.sleep(0.01)
        finally:
            await client.close()

        assert получено.get("результат") == SERVICE_RESULT, (
            "команда из обработчика события не получила ответ Home Assistant: "
            f"{получено.get('результат')!r}. Чтение сокета блокируется "
            "обработкой события, и ответ приходит только по таймауту — или не "
            "приходит вовсе"
        )

    @pytest.mark.asyncio
    async def test_events_keep_their_order(self) -> None:
        """Очередь не переставляет события: автоматы зависят от порядка."""
        client, soket = await _клиент()
        порядок: list[str] = []

        async def handler(payload: dict[str, Any]) -> None:
            порядок.append(payload["entity_id"])
            await asyncio.sleep(0.02)

        client._event_handler = handler
        try:
            for name in ("light.a", "light.b", "light.c"):
                await soket.incoming.put(
                    json.dumps(
                        {
                            "type": "event",
                            "event": {"event_type": "state_changed", "data": {"entity_id": name}},
                        }
                    )
                )
            for _ in range(200):
                if len(порядок) == 3:
                    break
                await asyncio.sleep(0.01)
        finally:
            await client.close()

        assert порядок == ["light.a", "light.b", "light.c"], f"порядок событий нарушен: {порядок}"
