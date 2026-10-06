"""`/ready` не должен объявлять готовность, когда соединения нет.

Готовность читается по флагу `is_connected`, и на живом стенде `/ready` отдавал
`ready: true` с пояснением «соединение установлено» в то время, когда соединения
не было (Known Issue #78). Причина та же, что у самого зависания: признак
соединения ставятся и снимаются в разных местах, и во время восстановления он
остаётся в состоянии, которое ничего не значит.

Три состояния, которые `/ready` обязан различать:

- попытка подключения идёт — соединения ещё нет, значит и готовности нет;
- соединение есть — готовность есть;
- соединение было и пропало — признак обрывается сразу, а не по факту
  следующей попытки.

Проверка идёт через настоящий цикл переподключения: подменённая заглушка
проверяла бы не то, что отдаёт `/ready` в бою.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

import adapters.ha_adapter as ha_adapter_module
from adapters.ha_adapter import HAAdapter
from webui.routes.readiness import check_home_assistant


class _UnreachableClient:
    """Клиент, подключение которого всегда падает: сеть недоступна."""

    def __init__(self, url: str, token: str, session: Any = None) -> None:
        """Создаёт клиента.

        Args:
            url: Адрес WebSocket.
            token: Токен доступа.
            session: Сессия (не используется).
        """
        self.url = url
        self.token = token
        self.session = session
        self.connected = False
        self._listen_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Не подключается.

        Raises:
            ConnectionError: Всегда — сети нет.
        """
        type(self).connect_calls += 1  # noqa: SLF001
        raise ConnectionError("сеть недоступна")

    async def subscribe(self, handler: Any, filter_dict: Any) -> None:
        """Никогда не вызывается.

        Args:
            handler: Обработчик событий.
            filter_dict: Фильтр подписки.

        Returns:
            Ничего.
        """
        raise AssertionError("subscribe не должен вызываться при недоступной сети")

    async def close(self) -> None:
        """Закрывает соединение.

        Returns:
            Ничего.
        """
        self.connected = False


@pytest.fixture
def unreachable(monkeypatch: pytest.MonkeyPatch) -> type[_UnreachableClient]:
    """Подменить клиента на недоступный и убрать паузы backoff.

    Returns:
        Класс подставного клиента.
    """
    _UnreachableClient.connect_calls = 0  # noqa: SLF001
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _UnreachableClient)

    real_sleep = asyncio.sleep

    async def _fast_sleep(_delay: float) -> None:
        """Ждёт минимально и уступает управление циклу событий.

        Args:
            _delay: Запрошенная пауза в секундах.

        Returns:
            Ничего.
        """
        await real_sleep(0)

    monkeypatch.setattr(ha_adapter_module.asyncio, "sleep", _fast_sleep)
    return _UnreachableClient


async def _wait_until(condition: Any, timeout: float = 3.0) -> bool:
    """Ждать выполнения условия.

    Args:
        condition: Проверяемое условие без аргументов.
        timeout: Предел ожидания в секундах.

    Returns:
        True, если условие выполнилось за отведённое время.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(0.01)
    return False


@pytest.mark.asyncio
async def test_readiness_reports_no_connection_while_reconnecting(
    unreachable: type[_UnreachableClient],
) -> None:
    """Пока идут попытки подключения, `/ready` сообщает об отсутствии соединения.

    Returns:
        Ничего.
    """
    adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
    await adapter.start()
    try:
        assert await _wait_until(lambda: unreachable.connect_calls >= 2)

        check = check_home_assistant(adapter)
        assert check["ok"] is False, (
            f"во время восстановления соединения /ready сообщил о нём как об "
            f"установленном: {check}. Оператор видит исправную систему там, где "
            f"события не приходят (Known Issue #78)"
        )
    finally:
        await adapter.stop()
