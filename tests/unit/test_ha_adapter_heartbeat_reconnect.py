"""Heartbeat объявляет переподключение, но не переподключается (Known Issue #70).

Симптом, замеченный в проде: за четыре часа работы в журнале адаптера появилась
ровно одна строка —

    HAAdapter: No events for 300s, connection is stale - forcing reconnect

— и ни одной попытки переподключения после неё. Heartbeat закрывает WebSocket-клиент
и продолжает цикл, полагая, что основной цикл это заметит. Не заметил.

Ранее закрытый путь висяния («задача чтения уже мертва к моменту ожидания») сюда не
относится: heartbeat идёт другим маршрутом, закрывая клиент из отдельной задачи.

Проверка моделирует ровно этот сценарий на настоящем коде адаптера: клиент, у
которого нет событий дольше порога. Ожидание — после «устаревшего» соединения
адаптер **сообщает об обрыве и планирует повторное подключение**. Если этого нет —
тест падает, и это ровно то, что происходит в проде.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any

import pytest

import adapters.ha_adapter as ha_adapter_module
from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient


class _StaleWebSocketClient(SimpleHAWebSocketClient):
    """Клиент без входящих событий: соединение «устаревает»."""

    def __init__(self, url: str, token: str, session: Any) -> None:
        """Создаёт клиента с фальшивым WebSocket.

        Args:
            url: Адрес WebSocket.
            token: Токен доступа.
            session: HTTP-сессия.
        """
        self.url = url
        self.token = token
        self.session = session
        self.connected = True
        self.ws = _FakeWS()
        self._listen_task: asyncio.Task[None] | None = None
        self.on_event: Any = None
        self.closed = False

    async def connect(self) -> bool:
        """Имитирует успешное подключение с живой задачей чтения.

        Returns:
            True.
        """
        self.connected = True
        # Задача чтения жива и спит: обрыв придёт из heartbeat, как в проде.
        self._listen_task = asyncio.create_task(asyncio.sleep(3600))
        return True

    async def subscribe(self, handler: Any, filter_dict: Any) -> None:
        """Имитирует подписку.

        Args:
            handler: Обработчик состояний.
            filter_dict: Фильтр событий.
        """

    async def close(self) -> None:
        """Закрывает клиент так же, как настоящий.

        Args:
            None.
        """
        self.closed = True
        if self._listen_task:
            self._listen_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listen_task
        self.connected = False


class _FakeWS:
    """Заглушка WebSocket-соединения."""

    closed = False

    async def close(self) -> None:
        """Имитирует закрытие соединения."""
        self.closed = True

    async def send_json(self, payload: dict[str, Any]) -> None:
        """Имитирует отправку.

        Args:
            payload: Сообщение.
        """

    async def ping(self) -> None:
        """Имитирует ping."""


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> HAAdapter:
    """Адаптер без хранилища и внешних подключений.

    Args:
        monkeypatch: Подмена значений.

    Returns:
        Готовый адаптер.
    """
    instance = HAAdapter.__new__(HAAdapter)
    instance._mode = "websocket"
    instance._ws_url = "ws://127.0.0.1:1/api/websocket"
    instance._token = "token"
    instance._shutdown_event = asyncio.Event()
    instance._reconnect_task = None
    instance._reconnect_attempt = 0
    instance._connected_once = True
    instance._ws_client = None
    instance._session = None
    # Событий не было давно: сразу попадаем в ветку «устарело».
    instance._last_event_time = time.time() - 1000
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _StaleWebSocketClient)
    return instance


async def test_stale_connection_should_trigger_reconnect(
    adapter: HAAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Устаревшее соединение должно приводить к фиксации обрыва и повтору подключения.

    Args:
        adapter: Экземпляр адаптера.
        monkeypatch: Подмена сна и очистки.
    """
    disconnects: list[str] = []
    monkeypatch.setattr(
        HAAdapter,
        "_record_disconnect",
        lambda self, reason, delay: disconnects.append(reason),
    )
    monkeypatch.setattr(HAAdapter, "_cleanup_websocket", _noop)

    async def _instant_sleep(_seconds: float) -> None:
        """Заменяет ожидание: тест не должен ждать 30 секунд реального времени.

        Args:
            _seconds: Запрошенная пауза.
        """

    monkeypatch.setattr(ha_adapter_module.asyncio, "sleep", _instant_sleep)

    attempts = 0

    async def _counting_connect(self: Any, *args: Any, **kwargs: Any) -> bool:
        """Считает попытки подключения и на третьей останавливает цикл.

        Args:
            self: Клиент.
            args: Позиционные аргументы.
            kwargs: Именованные аргументы.

        Returns:
            True.
        """
        nonlocal attempts
        attempts += 1
        if attempts >= 3:
            # Останавливаем цикл, чтобы тест не крутился вечно. Флаг живёт в
            # адаптере, а не в клиенте: клиент — отдельный объект.
            adapter._shutdown_event.set()
        return True

    monkeypatch.setattr(_StaleWebSocketClient, "connect", _counting_connect)

    await asyncio.wait_for(adapter._connect_websocket(), timeout=5)

    assert attempts >= 2, (
        f"после устаревшего соединения подключение не повторялось (попыток {attempts}). "
        "В проде это значит: heartbeat пишет «forcing reconnect», но переподключения "
        "не происходит — Known Issue #70"
    )
    assert disconnects, (
        "обрыв не зафиксирован ни в одном журнале: без этого и /ready, и сторож "
        "сообщают о расхождении молча"
    )


async def _noop(self: Any) -> None:
    """Заглушка вместо очистки соединения.

    Args:
        self: Не используется.
    """


class TestStalePathIsObservable:
    """Путь «устаревшее соединение» обязан оставлять след в журнале."""

    def test_should_log_before_and_after_closing_stale_connection(self) -> None:
        """Обе точки фиксируются: до закрытия и после.

        Без этого повторение дефекта выглядит как «лог пообещал переподключение и
        замолчал» — выяснять причину приходится вслепую. Именно это и стоило
        прошлого расследования (Known Issue #70).
        """
        source = (
            Path(__file__).resolve().parents[2] / "src" / "adapters" / "ha_adapter.py"
        ).read_text(encoding="utf-8")

        assert "closing stale connection" in source
        assert "stale connection closed" in source
        # Порядок важен: «после» должно идти после закрытия, иначе запись врёт.
        assert source.index("closing stale connection") < source.index("stale connection closed")
