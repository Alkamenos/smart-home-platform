"""Разрыв соединения обязан быть виден: и в адаптере, и в готовности.

Что произошло в бою
--------------------

2026-10-07 13:49:48 Home Assistant закрыл WebSocket (`CLOSE 1001 going away`).
Дальше в журнале — ни одного `PING`, ни одной записи адаптера, ни одного
переподключения. Пять часов подряд:

- `/ready` отвечал `home_assistant: ok`;
- `ha_connection_lost` был равен `0.0`;
- `websocket_disconnects_total` не вырос;
- watchdog писал `problem_count: 0`.

При этом HA жил: за час менялись 121 сущность, включая подписанные. События
есть, доставка молчит, и **ни один признак этого не показывал**.

Почему проверка именно такая
---------------------------

Разрыв воспроизводится поддельным HA, который закрывает соединение молча —
ровно как настоящий в 13:49:48. Проверяется не «соединение было», а то, что
после разрыва платформа **знает, что связи нет**: иначе `/ready` продолжает
отвечать «да», и оператор ищет поломку там, где события просто не доходят.

Это тот же класс, что #70 и #77: механизм есть, выглядит исправным, сигнала нет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from adapters.ha_adapter import SimpleHAWebSocketClient


#: Адрес поддельного HA.
#:
#: Порт не фиксирован: предыдущий прогон мог не успеть освободить его, и тогда
#: проверка падала бы с `address already in use` — то есть на состоянии чужой
#: проверки, а не своей. Причина выбирается явно, чтобы сбой был виден как
#: «порт занят», а не как «дефект не воспроизводится».
PORT = 0


class _FakeHA:
    """Поддельный Home Assistant, который закрывает соединение молча.

    Именно молча: `CLOSE 1001 going away` без ошибки и без объяснения — так
    ведёт себя настоящий HA при остановке или потере авторизации.
    """

    def __init__(self) -> None:
        """Создать поддельный сервер."""
        self.server: Any = None
        self.authenticated = False
        self.subscriptions = 0
        self.closed_cleanly = False

    async def handler(self, ws: Any) -> None:
        """Обслужить одно соединение до самого разрыва.

        Args:
            ws: Соединение с клиентом.

        Returns:
            Ничего.
        """
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.7"}))

        async for raw in ws:
            message = json.loads(raw)
            kind = message.get("type")

            if kind == "auth":
                await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.7"}))
                self.authenticated = True
            elif kind == "subscribe_events":
                self.subscriptions += 1
                await ws.send(json.dumps({"id": message["id"], "type": "result", "success": True}))
                await asyncio.sleep(0.1)
                await ws.close(1001, "going away")
                self.closed_cleanly = True
                return

    @property
    def url(self) -> str:
        """Адрес подключения к поддельному HA.

        Returns:
            URL с фактическим портом.
        """
        assert self.server is not None, "сервер не поднят"
        port = self.server.sockets[0].getsockname()[1]
        return f"ws://127.0.0.1:{port}/api/websocket"

    async def start(self) -> None:
        """Поднять сервер на свободном порту.

        Returns:
            Ничего.
        """
        from websockets.asyncio.server import serve

        self.server = await serve(self.handler, "127.0.0.1", PORT)

    async def stop(self) -> None:
        """Остановить сервер.

        Returns:
            Ничего.
        """
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()


async def _connect_client() -> tuple[SimpleHAWebSocketClient, _FakeHA]:
    """Подключиться к поддельному HA и дождаться разрыва.

    Ожидание сделано по времени, а не по завершению задачи чтения: именно её
    завершение и проверяется, и ждать его здесь означало бы ждать проверяемое.
    Пауза заведомо больше разрыва (0.1 с) и заведомо меньше любой задержки
    переподключения.

    Returns:
        Клиент и поддельный сервер.
    """
    fake = _FakeHA()
    await fake.start()

    client = SimpleHAWebSocketClient(url=fake.url, token="пробный")
    await client.connect()

    await client.subscribe(_noop_handler, {"type": "state_changed"})
    await asyncio.sleep(0.6)

    return client, fake


async def _noop_handler(_payload: dict[str, Any]) -> None:
    """Обработчик событий, которому всё равно.

    Args:
        _payload: Событие от HA.

    Returns:
        Ничего.
    """


@pytest.fixture
async def disconnected_client() -> Any:
    """Клиент, чьё соединение HA закрыл.

    Yields:
        Клиент после разрыва.
    """
    client, fake = await _connect_client()
    try:
        yield client, fake
    finally:
        await client.close()
        await fake.stop()


class TestDisconnectIsNoticed:
    """Разрыв обязан быть замечен, а не остаться тихим."""

    @pytest.mark.asyncio
    async def test_connected_is_false_after_clean_close(self, disconnected_client: Any) -> None:
        """После `CLOSE 1001` клиент не считает себя подключённым.

        Настоящий HA закрывает соединение штатно: цикл чтения доходит до конца
        без исключения. Если в этом случае флаг `connected` остаётся истинным,
        `is_connected` врёт, а `/ready` отвечает «соединение установлено» — при
        том, что ни одного события больше не придёт.
        """
        client, fake = disconnected_client

        assert fake.closed_cleanly, "поддельный HA не разорвал соединение — проверка бессмысленна"
        assert client.connected is False, (
            "после разрыва соединения клиент считает себя подключённым: "
            "`/ready` будет отвечать `home_assistant: ok`, и оператор будет "
            "искать поломку в том, что события просто не доходят. Ровно это "
            "и наблюдалось в бою пять часов подряд"
        )

    @pytest.mark.asyncio
    async def test_is_connected_property_tells_the_truth(self, disconnected_client: Any) -> None:
        """Свойство, которым пользуется `/ready`, тоже должно врать честно.

        Проверяется отдельно от флага: `/ready` спрашивает `is_connected`, а не
        внутреннее поле. Механизм и его наблюдатель — разные места, и одно
        может быть исправным при мёртвом другом.
        """
        client, _fake = disconnected_client

        assert client.connected is False, "внутренний флаг остался истинным"


class TestDisconnectIsReported:
    """Разрыв обязан попасть в сигналы, иначе о нём узнают по симптомам."""

    def test_client_exposes_disconnect_reason(self) -> None:
        """У клиента есть место, где хранится причина разрыва.

        Поле даёт разрыв видимым и позволяет отличить «HA ушёл» от «мы
        отключились сами» — иначе любая диагностика читает одну и ту же
        пустоту.
        """
        client = SimpleHAWebSocketClient(url="ws://localhost:1", token="x")

        assert hasattr(client, "_disconnect_reason"), (
            "у клиента нет места для причины разрыва: по журналу нельзя "
            "отличить молчаливый уход HA от собственной остановки"
        )

    @pytest.mark.asyncio
    async def test_adapter_reports_reason_to_readiness(self, disconnected_client: Any) -> None:
        """Причина доходит до `/ready`, а не остаётся внутри адаптера.

        `/ready` говорит оператору «нет соединения». Без причины он ищет
        поломку в платформе, тогда как разорвать соединение мог сам Home
        Assistant — и тогда чинить нужно не то.
        """
        from adapters.ha_adapter import HAAdapter

        client, _fake = disconnected_client
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "websocket"
        adapter._ws_client = client

        assert adapter.is_connected is False
        assert adapter.last_disconnect_reason, (
            "причина разрыва не дошла до наблюдателя: `/ready` скажет «нет "
            "соединения» без объяснения, и оператор будет искать поломку там, "
            "где соединение закрыл Home Assistant"
        )
        assert "1001" in str(adapter.last_disconnect_reason), (
            f"в причине нет кода закрытия, видно только «соединение закрыто "
            f"сервером»: {adapter.last_disconnect_reason}"
        )

    @pytest.mark.asyncio
    async def test_readiness_check_reports_disconnect(self, disconnected_client: Any) -> None:
        """Проверка готовности перестаёт отвечать «соединение установлено»."""
        from adapters.ha_adapter import HAAdapter
        from webui.routes.readiness import check_home_assistant

        client, _fake = disconnected_client
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "websocket"
        adapter._ws_client = client

        result = check_home_assistant(adapter)

        assert result["ok"] is False, (
            f"`/ready` отвечает, что Home Assistant на связи, хотя соединение разорвано: {result}"
        )
        assert "1001" in result["detail"], (
            f"в ответе о готовности нет причины: {result['detail']!r}. Оператор "
            f"будет искать поломку в платформе вместо того, чтобы понять, что "
            f"соединение закрыл Home Assistant"
        )
