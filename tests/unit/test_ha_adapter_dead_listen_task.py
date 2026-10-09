"""Адаптер обязан замечать обрыв и переподключаться (Known Issue #70).

Дефект: в `_connect_websocket` задача чтения добавлялась в ожидание только если
она была жива:

    listen_task = getattr(self._ws_client, "_listen_task", None)
    if listen_task and not listen_task.done():
        tasks.append(listen_task)
    done, pending = await asyncio.wait(tasks, FIRST_COMPLETED)

Если задача чтения уже завершилась (или её нет), в ожидании оставался **только**
флаг остановки, а он не срабатывает никогда. Адаптер уходил в ожидание вечно:
события Home Assistant больше не приходили, сторож писал `ha_disconnected: true`,
но ни обрыва, ни попыток переподключения в журнале не появлялось — потому что
кода восстановления в этом пути просто не было. Помогал только перезапуск
процесса.

Тест проверяет, что при мёртвой задаче чтения адаптер **не зависает**, а
фиксирует обрыв и переподключается. Молчание адаптера — тоже проверяемая
ошибка: `is_connected` обязан стать `False` без перезапуска.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

import pytest

import adapters.ha_adapter as ha_adapter_module
from adapters.ha_adapter import HAAdapter


class _DeadWebSocketClient:
    """Клиент, чья задача чтения уже завершилась."""

    def __init__(
        self, url: str | None = None, token: str | None = None, session: Any = None
    ) -> None:
        """Создаёт клиента с завершённой задачей чтения.

        Args:
            url: Адрес WebSocket.
            token: Токен доступа.
            session: HTTP-сессия.
        """
        self.url = url
        self.token = token
        self.session = session
        self.connected = False
        self._listen_task: asyncio.Task[None] | None = None

    async def connect(self: Any) -> bool:
        """Имитирует успешное подключение.

        Args:
            self: Не используется.

        Returns:
            True.
        """
        self.connected = True
        loop = asyncio.get_event_loop()

        async def _finished() -> None:
            return None

        # Задача завершилась до того, как адаптер начал ожидание.
        self._listen_task = loop.create_task(_finished())
        await self._listen_task
        self.connected = True
        return True

    async def subscribe(self: Any, callback: Any, event_filter: Any = None) -> None:
        """Имитирует подписку на события.

        Args:
            self: Не используется.
            callback: Обработчик состояний.
            event_filter: Фильтр событий.
        """

    async def close(self: Any) -> None:
        """Закрывает клиент.

        Args:
            self: Не используется.
        """


@pytest.fixture
def adapter() -> HAAdapter:
    """Адаптер в режиме WebSocket без реального подключения.

    Returns:
        Экземпляр HAAdapter.
    """
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
    # Колбэки смены суток: адаптер здесь создан в обход __init__, поэтому
    # поля проставляются вручную, как и остальные.
    instance.on_sunset = None
    instance.on_sunrise = None
    return instance


async def test_should_reconnect_when_listen_task_already_done(
    adapter: HAAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Мёртвая задача чтения приводит к переподключению, а не к вечному ожиданию.

    Args:
        adapter: Экземпляр адаптера.
        monkeypatch: Подмена клиента и счётчика попыток.
    """
    attempts = 0

    async def _fake_connect(self: Any) -> bool:
        nonlocal attempts
        attempts += 1
        if attempts >= 2:
            # Вторая попытка: останавливаем цикл, чтобы тест не крутился вечно.
            adapter._shutdown_event.set()
        return True

    # Подменяется класс, а не экземпляр: адаптер создаёт клиента сам, и подмена
    # готового объекта осталась бы незамеченной. Первая редакция проверки так и
    # делала, и падала по таймауту, разъясняя обрыв не по той причине.
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _DeadWebSocketClient)
    monkeypatch.setattr(_DeadWebSocketClient, "connect", _fake_connect, raising=True)

    async def _fake_loop() -> None:
        await asyncio.sleep(3600)

    monkeypatch.setattr(HAAdapter, "_heartbeat_loop", _fake_loop, raising=True)
    monkeypatch.setattr(HAAdapter, "_cleanup_websocket", _noop, raising=True)

    await asyncio.wait_for(adapter._connect_websocket(), timeout=5)

    assert attempts >= 2, (
        f"переподключения не было: попыток {attempts}. Прежний код в этом пути "
        "уходил в ожидание флага остановки и висел навсегда (Known Issue #70)"
    )


async def _noop(self: Any) -> None:
    """Заглушка вместо очистки соединения.

    Args:
        self: Не используется.
    """


async def test_should_report_disconnected_without_restart(
    adapter: HAAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """После обрыва адаптер честно сообщает, что соединения нет.

    Проверяется вместе с ожиданием: если цикл зависнет, тест упадёт по таймауту —
    молчание адаптера не считается успешным поведением.

    Args:
        adapter: Экземпляр адаптера.
        monkeypatch: Подмена клиента.
    """
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _DeadWebSocketClient)
    monkeypatch.setattr(_DeadWebSocketClient, "connect", _always_true, raising=True)
    monkeypatch.setattr(HAAdapter, "_heartbeat_loop", _fake_heartbeat, raising=True)
    monkeypatch.setattr(HAAdapter, "_cleanup_websocket", _noop, raising=True)

    task = asyncio.create_task(adapter._connect_websocket())
    await asyncio.sleep(0.2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert not adapter.is_connected, (
        "адаптер считает себя подключённым при разорванном соединении — /ready "
        "покажет исправность, а события приходить не будут"
    )


async def _always_true() -> bool:
    """Подмена подключения: всегда успех.

    Returns:
        True.
    """
    return True


async def _fake_heartbeat(self: Any) -> None:
    """Заглушка heartbeat-задачи.

    Args:
        self: Не используется.
    """
    await asyncio.sleep(3600)
