"""Тишина в доме не является признаком смерти соединения.

Heartbeat объявлял соединение устаревшим через 300 секунд после последнего
**события**. Но `_last_event_time` выставлялся только при подключении и нигде не
обновлялся — ни на входящем сообщении, ни на успешном ответе на ping. Поэтому:

- обрыв объявлялся ровно через 300 с после старта, независимо от активности дома
  (на живом стенде это повторилось в трёх прогонах подряд);
- исправное соединение рвалось каждые пять минут, а `/ready` успевал вернуть
  `ready: false` — то есть система сообщала об обрыве там, где его не было.

Признак жизни теперь обновляется тремя способами: при подключении, на каждом
входящем событии и на каждом успешном ответе на ping. Мёртвое соединение при этом
по-прежнему определяется: неудачный ping ставит `connected = False`, и это
проверяется отдельно.

Проверки берут настоящий код heartbeat: заглушка, которая «молчит», проверяла бы
не то, что происходит в адаптере.
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


class _WS:
    """Сокет, который отвечает на ping."""

    def __init__(self) -> None:
        """Создаёт заглушку.

        Returns:
            Ничего.
        """
        self.pings = 0

    async def ping(self) -> None:
        """Отвечает на ping.

        Returns:
            Ничего.
        """
        self.pings += 1


class _Client:
    """Клиент с сокетом и флагом подключения."""

    def __init__(self, ws: Any) -> None:
        """Создаёт клиента.

        Args:
            ws: Заглушка сокета.
        """
        self.ws = ws
        self.connected = True


def _adapter(now: float) -> HAAdapter:
    """Собирает адаптер для прогона heartbeat.

    Args:
        now: Текущее время, с которого отсчитывается «последний признак жизни».

    Returns:
        Готовый адаптер.
    """
    adapter = HAAdapter.__new__(HAAdapter)
    adapter._shutdown_event = asyncio.Event()
    adapter._ws_client = _Client(_WS())
    # Признак жизни был 400 секунд назад: при прежней логике это означало бы
    # немедленный обрыв, при новой — должен обновиться успешным ping.
    adapter._last_liveness_time = now - 400
    adapter._last_event_time = now - 400
    return adapter


@pytest.fixture
def one_iteration(monkeypatch: pytest.MonkeyPatch):
    """Позволяет прогнать ровно одну итерацию heartbeat.

    Цикл спит 30 с на итерацию, поэтому в тесте сон подменяется: иначе проверка
    шла бы минуты или висла. Подмена локальна для теста — счётчик итераций
    остаётся настоящим.

    Returns:
        Список с числом выполненных итераций.
    """
    iterations: list[int] = []

    def _factory(adapter: HAAdapter) -> Any:
        async def _instant_sleep(_seconds: float) -> None:
            """Ничего не ждёт и останавливает цикл после первой итерации."""
            iterations.append(1)
            if len(iterations) >= 1:
                adapter._shutdown_event.set()

        monkeypatch.setattr(ha_adapter_module.asyncio, "sleep", _instant_sleep)

    return _factory, iterations


@pytest.mark.asyncio
class TestQuietHomeIsNotDeadConnection:
    """Тишина не рвёт соединение."""

    async def test_successful_ping_refreshes_liveness(self, one_iteration: Any) -> None:
        """Ответ на ping обновляет признак жизни.

        Returns:
            Ничего.
        """
        adapter = _adapter(time.time())
        setup, iterations = one_iteration
        setup(adapter)

        await adapter._heartbeat_loop()  # noqa: SLF001

        assert iterations, "цикл не выполнил ни одной итерации"
        assert adapter._ws_client.ws.pings >= 1, "ping должен отправляться"
        assert adapter._last_liveness_time > time.time() - 100, (  # noqa: SLF001
            "успешный ответ на ping — прямое доказательство жизни соединения, "
            "но признак жизни не обновился: через 300 с исправное соединение "
            "снова было бы объявлено устаревшим"
        )

    async def test_silent_home_keeps_connection(self, one_iteration: Any) -> None:
        """Дом без событий не приводит к обрыву соединения.

        Returns:
            Ничего.
        """
        adapter = _adapter(time.time())
        setup, _ = one_iteration
        setup(adapter)

        await adapter._heartbeat_loop()  # noqa: SLF001

        assert adapter._ws_client.connected is True, (
            "тихий дом не должен рвать исправное соединение: обрыв был ложным и "
            "происходил каждые пять минут независимо от активности"
        )

    async def test_dead_connection_is_still_detected(self, one_iteration: Any) -> None:
        """Неотвечающий сокет по-прежнему приводит к обрыву.

        Returns:
            Ничего.
        """
        adapter = _adapter(time.time())
        setup, _ = one_iteration
        setup(adapter)

        class _DeadWS:
            """Сокет, который не отвечает."""

            async def ping(self) -> None:
                """Не отвечает.

                Raises:
                    TimeoutError: Всегда — соединение мертво.
                """
                raise TimeoutError("нет ответа")

        adapter._ws_client = _Client(_DeadWS())

        await adapter._heartbeat_loop()  # noqa: SLF001

        assert adapter._ws_client.connected is False, (
            "признак жизни обновляется на успешном ping, поэтому мёртвое "
            "соединение должно по-прежнему обнаруживаться: иначе починка тишины "
            "сломала бы исходную задачу heartbeat — найти мёртвое соединение"
        )
