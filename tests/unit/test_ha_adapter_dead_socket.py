"""Настоящая смерть сокета: heartbeat обнаруживает, но переподключения не происходит.

Сценарий #78: сокет умер не чистым закрытием, а «чёрной дырой» — как отвал Wi-Fi
или `docker network disconnect`. Разрыв такой, что ни FIN, ни RST не приходят:

- задача чтения **не завершается**: `recv()` ждёт данных, которых не будет
  никогда, и исключения не бросает;
- `ping` не получает ответа.

Написанный на это heartbeat ping действительно отвечает: он ставит
`connected = False`. Но на этом всё и останавливается.

Дыра в коде
-----------

1. Ветка «ping не ответил» (`ha_adapter.py`, `_heartbeat_loop`) ставит
   `connected = False` и делает `continue`. Сокет при этом **не закрывается**, а
   задача чтения **не отменяется**.
2. Цикл переподключения в это время стоит в `asyncio.wait([..., listen_task])`
   и ждёт, когда `listen_task` завершится. Он не завершится — сокета, который
   его разбудит, больше нет.
3. Следующая итерация heartbeat начинается с проверки
   `if not (self._ws_client and ... .connected): continue` — а `connected`
   только что became `False`. То есть heartbeat **сам себя выключил** и больше
   никогда ничего не проверит.

Итог: обрыв обнаружен, записан в журнал — и платформа навсегда остаётся без
событий. Переподключение, ради которого heartbeat и написан, не происходит
никогда. Именно это и наблюдалось на живом стенде: «цикл завис внутри итерации,
ни успеха, ни следующей попытки, помогает только перезапуск контейнера».

Проверки берут настоящий код heartbeat и настоящий цикл переподключения:
подменённые заглушки проверяли бы не то, что происходит в адаптере.
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


class _BlackHoleWS:
    """Сокет без ответа: пинги уходят в никуда, соединение не рвётся."""

    def __init__(self) -> None:
        """Создаёт заглушку.

        Returns:
            Ничего.
        """
        self.pings = 0

    async def ping(self) -> None:
        """Не отвечает на ping.

        Raises:
            TimeoutError: Всегда — ответа не будет никогда.
        """
        self.pings += 1
        raise TimeoutError("черная дыра: ответа нет")


class _BlackHoleClient:
    """Клиент, чьё соединение умерло молча.

    `connect()` проходит успешно (TCP и рукопожатие состоялись), но задача чтения
    потом не завершается никогда — ровно то поведение, которое даёт разрыв сокета
    без чистого закрытия.
    """

    connect_calls = 0
    close_calls = 0

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
        self.ws = _BlackHoleWS()
        self._listen_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Соединяется успешно.

        Returns:
            Ничего.
        """
        type(self).connect_calls += 1  # noqa: SLF001
        self.connected = True

    async def subscribe(self, handler: Any, filter_dict: Any) -> None:
        """Подписывается и запускает задачу чтения, которая не завершится.

        Args:
            handler: Обработчик событий.
            filter_dict: Фильтр подписки.

        Returns:
            Ничего.
        """
        self.subscription_confirmed = True
        self.subscription_error = None
        self.filtered_entity_ids = tuple(filter_dict.get("entity_ids", []))
        self._filtered_out = 0

        async def _listen_forever() -> None:
            """Ждёт данных, которых не придёт.

            Returns:
                Ничего.
            """
            await asyncio.Event().wait()

        self._listen_task = asyncio.create_task(_listen_forever())

    async def close(self) -> None:
        """Закрывает соединение.

        Returns:
            Ничего.
        """
        type(self).close_calls += 1  # noqa: SLF001
        self.connected = False
        if self._listen_task is not None and not self._listen_task.done():
            self._listen_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await self._listen_task


@pytest.fixture
def black_hole(monkeypatch: pytest.MonkeyPatch) -> type[_BlackHoleClient]:
    """Подменить клиента на «чёрную дыру» и ускорить циклы.

    Returns:
        Класс подставного клиента.
    """
    _BlackHoleClient.connect_calls = 0  # noqa: SLF001
    _BlackHoleClient.close_calls = 0  # noqa: SLF001
    monkeypatch.setattr(ha_adapter_module, "HomeAssistantWS", _BlackHoleClient)
    _speed_up_loops(monkeypatch)
    return _BlackHoleClient


def _speed_up_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать из проверок ожидания по 30 с (sleep heartbeat) и по 1–60 с (backoff).

    Подмена не ослабляет проверку: циклы по-прежнему выполняются настоящие, меняется
    только длительность пауз, иначе проверка шла бы минуты.

    Args:
        monkeypatch: Подмена sleep в модуле адаптера.
    """
    real_sleep = asyncio.sleep

    async def _fast_sleep(delay: float) -> None:
        """Ждёт минимально и уступает управление циклу событий.

        Args:
            delay: Запрошенная пауза в секундах.

        Returns:
            Ничего.
        """
        await real_sleep(0)

    monkeypatch.setattr(ha_adapter_module.asyncio, "sleep", _fast_sleep)


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
async def test_dead_socket_triggers_reconnect(
    black_hole: type[_BlackHoleClient],
) -> None:
    """Сокет, который не отвечает и не рвётся, обязан привести к переподключению.

    Returns:
        Ничего.
    """
    adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
    await adapter.start()
    try:
        reconnected = await _wait_until(lambda: black_hole.connect_calls >= 2)
        assert reconnected, (
            "heartbeat обнаружил мёртвое соединение, но переподключения не "
            "произошло: задача чтения не завершается на разрыве без чистого "
            "закрытия, цикл ждёт именно её, а heartbeat после неудачного пинга "
            "выключает себя проверкой `connected` — платформа остаётся без "
            "событий навсегда. Именно это наблюдалось на стенде: помогает только "
            "перезапуск контейнера."
        )
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_dead_socket_is_closed_not_just_flagged(
    black_hole: type[_BlackHoleClient],
) -> None:
    """Мёртвое соединение должно закрываться, а не только помечаться флагом.

    Returns:
        Ничего.
    """
    adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
    await adapter.start()
    try:
        closed = await _wait_until(lambda: black_hole.close_calls >= 1)
        assert closed, (
            "close() не вызывался ни разу: heartbeat только ставит connected = "
            "False. Сокет, помеченный флагом как мёртвый, остаётся открытым, "
            "и следующая проверка heartbeat его уже не увидит, потому что "
            "начинается с `if not connected: continue`"
        )
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_ready_stops_claiming_connection_when_socket_dies(
    black_hole: type[_BlackHoleClient],
) -> None:
    """`/ready` перестаёт сообщать об установленном соединении, когда сокет умер.

    На живом стенде `/ready` отдавал `ready: true` и «соединение установлено»
    при отсутствии соединения — оператор видел исправную систему там, где
    события не приходили. Проверка идёт через настоящий heartbeat: показанный
    дефект и состоял в том, что признак не сбрасывался.

    Returns:
        Ничего.
    """
    from webui.routes.readiness import check_home_assistant

    adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
    await adapter.start()
    try:
        assert await _wait_until(lambda: adapter.is_connected), (
            "исходное состояние не сложилось: соединение не считается установленным"
        )

        became_unready = await _wait_until(lambda: not adapter.is_connected)
        assert became_unready, (
            f"признак соединения остался истинным после смерти сокета, и /ready "
            f"продолжал отдавать {check_home_assistant(adapter)}: он читает флаг, "
            f"который никто не сбросил"
        )

        check = check_home_assistant(adapter)
        assert check["ok"] is False, f"/ready сообщил о соединении: {check}"
    finally:
        await adapter.stop()
