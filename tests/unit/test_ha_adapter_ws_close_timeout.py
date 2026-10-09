"""Закрытие WebSocket ограничено по времени (#70).

Живой стенд показал, где именно застревает `close()`: отмена задачи чтения
отрабатывает за 184 микросекунды, а `await self.ws.close()` не возвращается —
библиотека ждёт рукопожатия закрытия, которого на молчащем соединении не
приходит. Последствия были неприятными: heartbeat застревал, сокет оставался
открытым, переподключения не происходило, а `/ready` отвечал 200, то есть
платформа выглядела здоровой, уже не видя событий Home Assistant.

Проверка требует обеих сторон:

1. **Ограничение есть и работает** — на сокете, который не закрывается, `close()`
   возвращается за разумное время. Без этого висяние просто переедет в другое
   место.
2. **Штатное закрытие не сломано** — на нормальном сокете `close()` закрывает
   соединение и помечает клиента закрытым. Ограничение не должно превращать
   отказ закрытия в успех.

Заглушка «сокет, который не отдаёт закрытие» проверяет ограничение честно: она
имитирует молчащее соединение, а не исключение. Обработка исключения проходила
бы и без ограничения времени, то есть ничего бы не доказывала.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from adapters.ha_adapter import WS_CLOSE_TIMEOUT_SEC, SimpleHAWebSocketClient


class _SilentWS:
    """Сокет, который не закрывается — молчащее соединение.

    Именно это наблюдалось в проде: рукопожатие закрытия не приходит, и обычный
    `await self.ws.close()` не возвращается.
    """

    def __init__(self) -> None:
        """Создаёт заглушку.

        Returns:
            Ничего.
        """
        self.close_attempts = 0

    async def close(self) -> None:
        """Не возвращается, как и молчащее соединение.

        Returns:
            Ничего — никогда.
        """
        self.close_attempts += 1
        await asyncio.sleep(3600)


class _CooperativeWS:
    """Сокет, который закрывается штатно."""

    def __init__(self) -> None:
        """Создаёт заглушку.

        Returns:
            Ничего.
        """
        self.closed = False

    async def close(self) -> None:
        """Закрывает соединение.

        Returns:
            Ничего.
        """
        self.closed = True


def _client(ws: Any) -> SimpleHAWebSocketClient:
    """Собирает клиента с заданным сокетом и без задачи чтения.

    Args:
        ws: Заглушка сокета.

    Returns:
        Экземпляр клиента.
    """
    client = SimpleHAWebSocketClient.__new__(SimpleHAWebSocketClient)
    client.ws = ws
    client._listen_task = None
    client.connected = True
    return client


class TestCloseTimeout:
    """Ограничение закрытия."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_should_return_when_websocket_never_closes(self) -> None:
        """На молчащем сокете `close()` возвращается за разумное время.

        Без ограничения этот тест падал бы по таймауту теста — то есть ровно то
        висяние, которое наблюдалось в проде.

        Args:
            None.
        """
        client = _client(_SilentWS())

        started = time.monotonic()
        await asyncio.wait_for(client.close(), timeout=WS_CLOSE_TIMEOUT_SEC + 5)
        elapsed = time.monotonic() - started

        assert elapsed < WS_CLOSE_TIMEOUT_SEC + 2, (
            f"close() ждал {elapsed:.1f} с — он должен ограничиваться таймаутом "
            f"{WS_CLOSE_TIMEOUT_SEC} с, иначе висяние просто переедет (Known Issue #70)"
        )
        assert client.connected is False, (
            "после close() клиент остался «подключённым»: основной цикл увидит "
            "живое соединение и не начнёт переподключение"
        )

    @pytest.mark.asyncio
    async def test_should_still_close_working_websocket(self) -> None:
        """Штатное закрытие работает: сокет закрыт, клиент помечен закрытым.

        Args:
            None.
        """
        ws = _CooperativeWS()
        client = _client(ws)

        await asyncio.wait_for(client.close(), timeout=WS_CLOSE_TIMEOUT_SEC)

        assert ws.closed is True, "ограничение по времени не должно мешать штатному закрытию"
        assert client.connected is False
