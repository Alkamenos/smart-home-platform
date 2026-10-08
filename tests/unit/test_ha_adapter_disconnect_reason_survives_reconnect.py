"""Причина обрыва обязана переживать cleanup и попытки восстановления (B29).

Живой прогон 2026-10-08: контейнер отключён от сети на 45 с
(17:17:14–17:17:59), опрос `/ready` каждые ~0.5 с изнутри контейнера,
140 сэмплов:

- обрыв замечен: 20 сэмплов `ha_ok: False` («нет соединения с Home
  Assistant»), восстановление через 4 с после возврата сети;
- но **ни один** сэмпл не содержал причину: `grep -c "(" = 0`.

Журнал причину пишет (`listen loop finished (ConnectionClosedError:
sent 1011 ... keepalive ping timeout)`, `WebSocket lost (listen task
ended)`), а `/ready` — нет. Причина живёт на клиенте, и она не доживает
до наблюдателя:

- `finally: _cleanup_websocket()` обнуляет `_ws_client` →
  `last_disconnect_reason` возвращает `None`;
- каждая попытка восстановления создаёт нового клиента с пустой
  причиной.

Ранее причина была видна миллисекунды — окно между смертью listen loop
и `finally`. Существующие тесты (`test_websocket_disconnect_visible.py`)
проверяют свойство на живом клиенте через `__new__` и этот жизненный
цикл не проходят.

Проверяется свойство `last_disconnect_reason` и его наблюдатель
`check_home_assistant` — ровно тот путь, который оператор видит в
`/ready` во время реального обрыва.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient
from webui.routes.readiness import check_home_assistant


#: Причина, которую на живом обрыве записывает listen loop клиента.
LIVE_REASON = (
    "ConnectionClosedError: sent 1011 (internal error) keepalive ping "
    "timeout; no close frame received"
)


def _adapter_with_broken_client() -> tuple[HAAdapter, SimpleHAWebSocketClient]:
    """Собрать адаптер с клиентом, чей listen loop только что умер.

    Ровно то состояние, в котором адаптер оказывается сразу после обрыва
    на живом стенде: клиент помнит причину, флаг соединения снят.

    Returns:
        Адаптер и клиент с записанной причиной разрыва.
    """
    adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
    client = SimpleHAWebSocketClient(url="ws://fake-ha:8123", token="t")
    client.connected = False
    client._disconnect_reason = LIVE_REASON  # noqa: SLF001
    adapter._ws_client = client  # noqa: SLF001
    return adapter, client


class TestReasonSurvivesCleanup:
    """Причина обязана остаться видимой, когда мёртвый клиент убран."""

    @pytest.mark.asyncio
    async def test_reason_is_visible_after_client_cleanup(self) -> None:
        """После cleanup `/ready` всё ещё называет причину обрыва.

        `finally` цикла переподключения обнуляет `_ws_client`: без
        хранения на адаптере наблюдатель теряет причину ровно в тот
        момент, когда оператору важно, кто разорвал соединение.
        """
        adapter, _client = _adapter_with_broken_client()

        adapter._record_disconnect("listen task ended", 1.0)  # noqa: SLF001
        await adapter._cleanup_websocket()  # noqa: SLF001

        result = check_home_assistant(adapter)
        assert result["ok"] is False
        assert "keepalive ping timeout" in result["detail"], (
            f"после cleanup причина потеряна, оператор видит безликое "
            f"«нет соединения»: {result['detail']!r}. Живой обрыв 2026-10-08: "
            f"20 сэмплов подряд без единой причины"
        )

    @pytest.mark.asyncio
    async def test_reason_survives_new_client_replacement(self) -> None:
        """Причина переживает создание нового клиента при попытке ретрая.

        Каждая итерация цикла переподключения создаёт свежего клиента с
        пустой причиной: на клиенте она не доживает и до второй попытки
        восстановления, то есть практически ни до какого момента
        реального обрыва.
        """
        adapter, _client = _adapter_with_broken_client()

        adapter._record_disconnect("listen task ended", 1.0)  # noqa: SLF001
        await adapter._cleanup_websocket()  # noqa: SLF001
        adapter._ws_client = SimpleHAWebSocketClient(  # noqa: SLF001
            url="ws://fake-ha:8123", token="t"
        )

        assert "keepalive ping timeout" in str(adapter.last_disconnect_reason), (
            f"новый клиент затёр причину обрыва: {adapter.last_disconnect_reason!r}"
        )

    @pytest.mark.asyncio
    async def test_stored_reason_is_client_cause_not_generic_fallback(self) -> None:
        """Хранится первопричина клиента, а не обобщённое «listen task ended».

        Классификация `_listen_task_reason` видит только пустой результат
        задачи: исключение listen loop проглатывает сам цикл чтения.
        Оператору нужен корень (`keepalive ping timeout`), а не след
        механизма.
        """
        adapter, _client = _adapter_with_broken_client()

        adapter._record_disconnect("listen task ended", 1.0)  # noqa: SLF001
        await adapter._cleanup_websocket()  # noqa: SLF001

        assert adapter.last_disconnect_reason == LIVE_REASON, (
            f"вместо первопричины сохранено обобщение: {adapter.last_disconnect_reason!r}"
        )


class TestReasonDuringRecoveryAttempts:
    """Во время восстановления оператор видит причину обрыва, а не симптом."""

    @pytest.mark.asyncio
    async def test_later_connect_errors_do_not_overwrite_break_reason(self) -> None:
        """Неудачные попытки подключения не затирают причину обрыва.

        Текст ошибки ретрая (`WebSocket connect() succeeded but
        connected=False`) вводит в заблуждение: он ничего не говорит о
        том, что соединение убил обрыв сети, и прячет первопричину.
        """
        adapter, _client = _adapter_with_broken_client()

        adapter._record_disconnect("listen task ended", 1.0)  # noqa: SLF001
        await adapter._cleanup_websocket()  # noqa: SLF001
        adapter._ws_client = SimpleHAWebSocketClient(  # noqa: SLF001
            url="ws://fake-ha:8123", token="t"
        )
        adapter._record_disconnect(  # noqa: SLF001
            "ConnectionError: WebSocket connect() succeeded but connected=False",
            2.0,
        )

        assert "keepalive ping timeout" in str(adapter.last_disconnect_reason), (
            f"ошибка попытки подключения перекрыла причину обрыва: "
            f"{adapter.last_disconnect_reason!r}"
        )

    def test_connect_error_is_visible_when_never_connected(self) -> None:
        """Платформа, стартовавшая при мёртвой сети, тоже объясняет себя.

        Ни одного успешного соединения не было, клиента с причиной не
        существует — без хранения на адаптере `/ready` отвечает тем же
        безличным «нет соединения», что и при обрыве.
        """
        adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")

        adapter._record_disconnect(  # noqa: SLF001
            "ConnectionError: сеть недоступна", 1.0
        )

        result = check_home_assistant(adapter)
        assert "сеть недоступна" in result["detail"], (
            f"причина стартовой ошибки не дошла до /ready: {result['detail']!r}"
        )

    def test_reason_is_cleared_after_successful_connection(self) -> None:
        """Успешное подключение сбрасывает причину прошлого обрыва.

        Хранение «первой причины» без сброса показало бы оператору во
        время нового обрыва причину старого — следующий инцидент
        выглядел бы как тот же самый.
        """
        adapter = HAAdapter(mode="websocket", ws_url="ws://fake-ha:8123", token="t")
        adapter._record_disconnect("ConnectionError: сеть недоступна", 1.0)  # noqa: SLF001

        adapter._mark_connection_established()  # noqa: SLF001

        assert adapter.last_disconnect_reason is None, (
            f"после успешного подключения причина не сброшена: "
            f"{adapter.last_disconnect_reason!r} — следующий обрыв будет "
            f"объяснён причиной прошлого"
        )
