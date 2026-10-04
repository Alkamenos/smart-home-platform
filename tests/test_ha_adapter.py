"""
Tests for HA Adapter - Home Assistant Communication Layer

These tests verify the adapter's behavior according to specification:
- Dual-mode operation (Pyscript and WebSocket)
- State change event publishing with trace_id
- Service call execution with error handling
- Graceful shutdown and reconnection logic
- Manual lockout integration via ControlTracker
- EventRouter integration for sensor routing
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient


#: Ожидаемая последовательность пауз экспоненциального отката: старт 1 с,
#: удвоение до потолка 60 с. Семь значений — при шести последнее равно 32 и
#: ветка насыщения `min(..., 60.0)` не достигается, поэтому проверка потолка
#: была бы пустой и тест прошёл бы даже при потолке в 10 секунд.
EXPECTED_BACKOFF = [1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]


class TestHAAdapterInitialization:
    """Test HAAdapter initialization and configuration validation."""

    def test_init_pyscript_mode_requires_hass(self):
        """Pyscript mode must have hass instance provided."""
        with pytest.raises(ValueError, match="hass instance is required for pyscript mode"):
            HAAdapter(mode="pyscript", engine=None, hass=None)

    def test_init_websocket_mode_requires_ws_url(self):
        """WebSocket mode must have ws_url provided."""
        with pytest.raises(ValueError, match="ws_url is required for websocket mode"):
            HAAdapter(mode="websocket", ws_url=None, token="test_token")

    def test_init_websocket_mode_requires_token(self):
        """WebSocket mode must have token provided."""
        with pytest.raises(ValueError, match="token is required for websocket mode"):
            HAAdapter(mode="websocket", ws_url="ws://localhost:8123", token=None)

    def test_init_invalid_mode_raises_error(self):
        """Invalid mode should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid mode"):
            HAAdapter(mode="invalid_mode", hass=MagicMock())

    def test_init_pyscript_mode_success(self):
        """Pyscript mode initializes successfully with hass."""
        hass_mock = MagicMock()
        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)
        assert adapter.mode == "pyscript"
        assert adapter.is_connected is True

    def test_init_websocket_mode_success(self):
        """WebSocket mode initializes successfully with credentials."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )
        assert adapter.mode == "websocket"
        assert adapter.is_connected is False

    def test_init_generates_unique_trace_ids(self):
        """Each trace_id should be unique (8-char UUID prefix)."""
        hass_mock = MagicMock()
        adapter = HAAdapter(mode="pyscript", hass=hass_mock)
        trace_id_1 = adapter._generate_trace_id()
        trace_id_2 = adapter._generate_trace_id()
        assert len(trace_id_1) == 8
        assert trace_id_1 != trace_id_2


class TestHAAdapterStateChangeHandling:
    """Test state change event processing and publishing."""

    @pytest.mark.asyncio
    async def test_on_state_change_publishes_to_event_bus(self):
        """State changes should be published to EventBus with trace_id."""
        hass_mock = MagicMock()
        engine_mock = MagicMock()
        engine_mock.event_bus = MagicMock()
        engine_mock.event_bus.publish = AsyncMock()

        adapter = HAAdapter(mode="pyscript", engine=engine_mock, hass=hass_mock)

        await adapter.on_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        engine_mock.event_bus.publish.assert_called_once()
        call_args = engine_mock.event_bus.publish.call_args
        assert call_args.kwargs["event_type"] == "state_change"
        assert "trace_id" in call_args.kwargs
        payload = call_args.kwargs["payload"]
        assert payload["entity_id"] == "binary_sensor.kitchen_motion"
        assert payload["new_state"] == "on"
        assert payload["old_state"] == "off"

    @pytest.mark.asyncio
    async def test_on_state_change_with_existing_trace_id(self):
        """Existing trace_id from context should be preserved."""
        hass_mock = MagicMock()
        engine_mock = MagicMock()
        engine_mock.event_bus = MagicMock()
        engine_mock.event_bus.publish = AsyncMock()

        adapter = HAAdapter(mode="pyscript", engine=engine_mock, hass=hass_mock)

        await adapter.on_state_change(
            entity_id="binary_sensor.motion",
            new_state="on",
            old_state="off",
            context={"trace_id": "custom123"},
        )

        call_args = engine_mock.event_bus.publish.call_args
        assert call_args.kwargs["trace_id"] == "custom123"

    @pytest.mark.asyncio
    async def test_on_state_change_records_manual_control(self):
        """Manual control events should be recorded via ControlTracker."""
        hass_mock = MagicMock()
        middleware_mock = MagicMock()
        middleware_mock.record_manual_control = MagicMock()

        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=hass_mock,
            manual_lockout_middleware=middleware_mock,
        )

        await adapter.on_state_change(
            entity_id="light.kitchen",
            new_state="on",
            old_state="off",
            context={"user_id": "user_123"},
        )

        middleware_mock.record_manual_control.assert_called_once_with("light.kitchen")

    @pytest.mark.asyncio
    async def test_on_state_change_without_user_id_no_lockout(self):
        """No manual lockout recording if user_id is absent."""
        hass_mock = MagicMock()
        middleware_mock = MagicMock()

        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=hass_mock,
            manual_lockout_middleware=middleware_mock,
        )

        await adapter.on_state_change(
            entity_id="light.kitchen",
            new_state="on",
            old_state="off",
            context={},
        )

        middleware_mock.record_manual_control.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_state_change_routes_via_event_router(self):
        """State changes should be routed through EventRouter if available."""
        hass_mock = MagicMock()
        event_router_mock = MagicMock()
        event_router_mock.route_state_change = AsyncMock()

        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=hass_mock,
            event_router=event_router_mock,
        )

        await adapter.on_state_change(
            entity_id="binary_sensor.motion",
            new_state="on",
            old_state="off",
            context={},
        )

        event_router_mock.route_state_change.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_state_change_handles_event_bus_exception(self):
        """EventBus exceptions should be logged but not crash the adapter."""
        hass_mock = MagicMock()
        engine_mock = MagicMock()
        engine_mock.event_bus = MagicMock()
        engine_mock.event_bus.publish = AsyncMock(side_effect=Exception("EventBus error"))

        adapter = HAAdapter(mode="pyscript", engine=engine_mock, hass=hass_mock)

        # Should not raise exception
        result = await adapter.on_state_change(
            entity_id="binary_sensor.motion",
            new_state="on",
            old_state="off",
            context={},
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_on_state_change_fallback_to_direct_trigger(self):
        """If no event_bus, should trigger FSM directly."""
        import builtins

        hass_mock = MagicMock()
        engine_mock = MagicMock()

        # Mock hasattr to return False for event_bus attribute
        original_hasattr = builtins.hasattr

        def mock_hasattr(obj, name):
            if obj is engine_mock and name == "event_bus":
                return False
            return original_hasattr(obj, name)

        engine_mock.trigger = AsyncMock()

        with patch("builtins.hasattr", side_effect=mock_hasattr):
            adapter = HAAdapter(mode="pyscript", engine=engine_mock, hass=hass_mock)

            await adapter.on_state_change(
                entity_id="binary_sensor.motion",
                new_state="on",
                old_state="off",
                context={},
            )

            engine_mock.trigger.assert_called_once()
            call_args = engine_mock.trigger.call_args
            assert call_args.kwargs["entity_id"] == "binary_sensor.motion"
            assert call_args.kwargs["event"] == "binary_sensor.motion_changed"


class TestHAAdapterServiceCalls:
    """Test service call execution in both modes."""

    @pytest.mark.asyncio
    async def test_call_service_pyscript_mode_success(self):
        """Pyscript mode should call hass.services.async_call."""
        hass_mock = MagicMock()
        hass_mock.services.async_call = AsyncMock()

        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
            data={"brightness": 255},
            trace_id="test123",
        )

        assert result is True
        hass_mock.services.async_call.assert_called_once_with(
            domain="light",
            service="turn_on",
            service_data={"brightness": 255, "entity_id": "light.kitchen"},
        )

    @pytest.mark.asyncio
    async def test_call_service_pyscript_mode_no_hass(self):
        """Pyscript mode without hass should return False."""
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "pyscript"
        adapter._hass = None
        adapter._generate_trace_id = lambda: "test123"

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_call_service_pyscript_mode_exception_handling(self):
        """Service call exceptions should be caught and logged."""
        hass_mock = MagicMock()
        hass_mock.services.async_call = AsyncMock(side_effect=Exception("HA error"))

        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_call_service_websocket_mode_success(self):
        """WebSocket mode should call ws_client.call_service."""
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "websocket"
        adapter._ws_client = MagicMock()
        adapter._ws_client.call_service = AsyncMock(return_value={"result": "success"})
        adapter._generate_trace_id = lambda: "test123"

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
            data={"brightness": 100},
        )

        assert result is True
        adapter._ws_client.call_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_service_websocket_mode_no_client(self):
        """WebSocket mode without client should return False."""
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "websocket"
        adapter._ws_client = None
        adapter._generate_trace_id = lambda: "test123"

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_call_service_websocket_mode_exception(self):
        """WebSocket service call exceptions should be caught."""
        adapter = HAAdapter.__new__(HAAdapter)
        adapter._mode = "websocket"
        adapter._ws_client = MagicMock()
        adapter._ws_client.call_service = AsyncMock(side_effect=Exception("WS error"))
        adapter._generate_trace_id = lambda: "test123"

        result = await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_call_service_empty_data_defaults(self):
        """Empty data should default to empty dict."""
        hass_mock = MagicMock()
        hass_mock.services.async_call = AsyncMock()

        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
            data=None,
        )

        call_args = hass_mock.services.async_call.call_args
        assert call_args.kwargs["service_data"] == {"entity_id": "light.kitchen"}


class TestHAAdapterWebSocketLifecycle:
    """Test WebSocket connection lifecycle management."""

    @pytest.mark.asyncio
    async def test_start_pyscript_mode_is_noop(self):
        """start() should be no-op in pyscript mode."""
        hass_mock = MagicMock()
        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        await adapter.start()

        # Should complete immediately without creating tasks

    @pytest.mark.asyncio
    async def test_start_websocket_mode_creates_task(self):
        """WebSocket mode should create background connection task."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        with patch.object(adapter, "_connect_websocket", new_callable=AsyncMock) as mock_connect:
            await adapter.start()
            await asyncio.sleep(0.1)  # Allow task to start

            mock_connect.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_reconnect_task(self):
        """stop() should cancel pending reconnect task."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        # Create a mock reconnect task that behaves like a real asyncio.Task
        async def dummy_coro():
            pass

        mock_task = asyncio.create_task(dummy_coro())
        mock_task.cancel = MagicMock()  # Override cancel to track calls
        adapter._reconnect_task = mock_task

        await adapter.stop()

        mock_task.cancel.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cleanup_websocket_in_websocket_mode(self):
        """stop() should cleanup WebSocket resources."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        mock_ws_client = AsyncMock()
        mock_session = AsyncMock()
        adapter._ws_client = mock_ws_client
        adapter._session = mock_session

        await adapter.stop()

        mock_ws_client.close.assert_awaited_once()
        mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_websocket_exponential_backoff(self):
        """WebSocket reconnection should use exponential backoff.

        Тест был заглушкой: он объявлял `failing_connect()`, **ни разу её не
        вызывал** и заканчивался `pass` с комментарием «requires more complex
        mocking». Экспоненциальный откат не проверялся нигде, хотя он заявлен в
        описании модуля.

        Проверяется **вся** последовательность задержек: 1, 2, 4, 8, 16, 32, 60.
        Число попыток взято семь, а не шесть: при шести последняя пауза равна 32,
        ветка насыщения `min(..., 60.0)` не достигается, и проверка потолка
        становится пустой — тест прошёл бы и при потолке в 10 секунд.

        Паузы перехватываются, поэтому тест выполняется за миллисекунды и не
        ждёт реальных пауз.
        """
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        observed_delays: list[float] = []
        # Ссылка на исходный sleep захватывается ДО подмены: патчится атрибут
        # реального модуля asyncio, иначе получить оригинал уже нельзя.
        real_sleep = asyncio.sleep

        failing_client = AsyncMock()
        failing_client.connect.side_effect = ConnectionError("Connection failed")
        failing_client.connected = False

        attempts = {"count": 0}

        async def counting_sleep(delay, *args, **kwargs):
            """Записывает паузу и останавливает цикл на седьмой попытке."""
            observed_delays.append(delay)
            attempts["count"] += 1
            if attempts["count"] >= len(EXPECTED_BACKOFF):
                adapter._shutdown_event.set()
            return await real_sleep(0, *args, **kwargs)

        with (
            patch.object(adapter, "_get_logger", return_value=MagicMock()),
            patch("src.adapters.ha_adapter.HomeAssistantWS", return_value=failing_client),
            patch("src.adapters.ha_adapter.aiohttp.ClientSession"),
            patch("src.adapters.ha_adapter.asyncio.sleep", new=counting_sleep),
        ):
            await adapter._connect_websocket()

        assert observed_delays == EXPECTED_BACKOFF, (
            f"последовательность пауз должна удваиваться до потолка 60 с, получено {observed_delays}"
        )


#: Таймаут ожидания ответа на команду HA, зашитый в `SimpleHAWebSocketClient`.
#: Тесты перехватывают `asyncio.wait_for` и проверяют это значение, но никогда
#: не ждут его по-настоящему.
HA_RESPONSE_TIMEOUT = 15


class FakeHAWebSocket:
    """Заглушка сокета, повторяющая контракт, который использует клиент.

    `SimpleHAWebSocketClient` читает входящие кадры **только** фоновой задачей
    `_listen_loop` (`async for raw in self.ws`). Ни `get_states()`, ни
    `call_service()` не вызывают `recv()`: они регистрируют обработчик в
    `_handlers[msg_id]` и ждут future, который резолвит `_listen_loop`.

    Поэтому заглушка обязана поддерживать асинхронную итерацию, а подмена
    `recv` бессмысленна — см. `test_ws_client_get_states_reads_via_listen_loop`.

    Args:
        responder: Вызывается на каждый отправленный запрос; возвращает кадр,
            который сервер «шлёт» в ответ (или `None`, чтобы не отвечать).
    """

    def __init__(self, responder=None):
        self._incoming: asyncio.Queue[str] = asyncio.Queue()
        self._responder = responder
        #: Разобранные запросы, ушедшие через `send()`.
        self.sent: list[dict] = []
        #: Вызовы `recv()`: их не должно быть ни одного (см. докстринг).
        self.recv_calls: list[str] = []
        self.closed = False

    async def send(self, raw: str) -> None:
        """Принимает запрос клиента и, если задан `responder`, отвечает на него."""
        request = json.loads(raw)
        self.sent.append(request)
        if self._responder is not None:
            frame = self._responder(request)
            if frame is not None:
                self.push(frame)

    def push(self, message: dict) -> None:
        """Кладёт кадр во входящую очередь (неблокирующий вызов)."""
        self._incoming.put_nowait(json.dumps(message))

    async def recv(self) -> str:
        """Ловушка для `recv`: клиент не должен читать кадры напрямую."""
        self.recv_calls.append("recv")
        return await self._incoming.get()

    def __aiter__(self) -> "FakeHAWebSocket":
        return self

    async def __anext__(self) -> str:
        """Отдаёт кадр из очереди; при пустой очереди — ждёт нового, как живой сокет."""
        return await self._incoming.get()

    async def close(self) -> None:
        self.closed = True


class TestSimpleHAWebSocketClient:
    """Test the simple WebSocket client implementation."""

    @pytest.mark.asyncio
    async def test_ws_client_connect_auth_flow(self):
        """WebSocket client should complete auth handshake."""
        with patch("websockets.connect", new_callable=AsyncMock) as mock_ws_connect:
            mock_ws = AsyncMock()
            mock_ws_connect.return_value = mock_ws

            # Mock auth_required message
            mock_ws.recv = AsyncMock(
                side_effect=[
                    '{"type": "auth_required"}',
                    '{"type": "auth_ok"}',
                ]
            )

            client = SimpleHAWebSocketClient(
                url="ws://localhost:8123",
                token="test_token",
            )

            await client.connect()

            assert client.connected is True
            mock_ws.send.assert_called()

    @pytest.mark.asyncio
    async def test_ws_client_connect_auth_failure(self):
        """Auth failure should set connected to False."""
        with patch("websockets.connect", new_callable=AsyncMock) as mock_ws_connect:
            mock_ws = AsyncMock()
            mock_ws_connect.return_value = mock_ws

            mock_ws.recv = AsyncMock(
                side_effect=[
                    '{"type": "auth_required"}',
                    '{"type": "auth_invalid"}',
                ]
            )

            client = SimpleHAWebSocketClient(
                url="ws://localhost:8123",
                token="invalid_token",
            )

            await client.connect()

            assert client.connected is False

    @pytest.mark.asyncio
    async def test_ws_client_subscribe_sends_message(self):
        """subscribe() should send subscription message to WS."""
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = AsyncMock()
        client.connected = True

        handler_mock = AsyncMock()
        await client.subscribe(handler_mock, {"type": "state_changed"})

        client.ws.send.assert_called_once()
        sent_data = client.ws.send.call_args[0][0]
        assert "subscribe_events" in sent_data

    @pytest.mark.asyncio
    async def test_ws_client_get_states_returns_result(self):
        """get_states() returns the exact result delivered by the listen loop.

        Тест был вакуумным: он подменял `ws.recv` (который `get_states()` не
        вызывает вообще) и проверял лишь `isinstance(states, list)` — то есть
        проходил и для пустого `[]`, возвращённого по таймауту. 15 секунд
        ожидания при этом реально тратились.

        Теперь заглушка отвечает на `get_states` так же, как HA: сообщением типа
        `result` с тем же `id`, а ответ доставляется через настоящий
        `_listen_loop`. Проверяется посимвольное содержимое ответа и то, что
        запрос ушёл в сокет в правильном формате протокола.
        """
        payload = [
            {"entity_id": "light.kitchen", "state": "on", "attributes": {"brightness": 255}},
            {"entity_id": "binary_sensor.motion", "state": "off", "attributes": {}},
        ]

        def responder(request: dict) -> dict:
            return {"id": request["id"], "type": "result", "success": True, "result": payload}

        ws = FakeHAWebSocket(responder=responder)
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = ws
        client.connected = True
        client._listen_task = asyncio.create_task(client._listen_loop())

        try:
            states = await client.get_states()
        finally:
            await client.close()

        # Запрос отправлен ровно один раз и в формате протокола HA.
        assert ws.sent == [{"id": 1, "type": "get_states"}]
        # Ответ разобран по полям, а не «по факту это список».
        assert states == payload
        assert [state["entity_id"] for state in states] == [
            "light.kitchen",
            "binary_sensor.motion",
        ]
        assert states[0]["attributes"]["brightness"] == 255
        # Обработчик из `_handlers` снят listen loop'ом — ответ доставлен по id.
        assert client._handlers == {}
        assert ws.recv_calls == []

    @pytest.mark.asyncio
    async def test_ws_client_get_states_timeout(self):
        """get_states(): молчащий сервер → пустой список, без 15 секунд ожидания.

        Тест ждал настоящий таймаут из production-кода, то есть 15 секунд на
        каждый прогон. Теперь `asyncio.wait_for` перехватывается: реальная
        функция вызывается с сокращённым таймаутом, поэтому проверяется подлинный
        путь отмены future и подлинный `except TimeoutError`, а тест занимает
        миллисекунды. Значение таймаута из кода при этом фиксируется и
        сравнивается с ожидаемым.
        """
        ws = FakeHAWebSocket()  # сервер не отвечает: responder не задан
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = ws
        client.connected = True
        client._listen_task = asyncio.create_task(client._listen_loop())

        real_wait_for = asyncio.wait_for
        requested_timeouts: list[float] = []

        async def shortened_wait_for(awaitable, timeout):
            """Запоминает таймаут из production-кода и сжимает его до 10 мс."""
            requested_timeouts.append(timeout)
            return await real_wait_for(awaitable, timeout=0.01)

        try:
            with patch(
                "src.adapters.ha_adapter.asyncio.wait_for",
                new=shortened_wait_for,
            ):
                states = await client.get_states()
        finally:
            await client.close()

        assert states == []
        assert requested_timeouts == [HA_RESPONSE_TIMEOUT]
        # Запрос всё равно ушёл в сокет — таймаут не подменяет отправку.
        assert ws.sent == [{"id": 1, "type": "get_states"}]

    @pytest.mark.asyncio
    async def test_ws_client_get_states_reads_via_listen_loop(self):
        """Фиксирует фактический контракт: `recv()` не вызывается никогда.

        Обе прежние версии тестов подменяли `ws.recv`, считая, что `get_states()`
        читает ответ сокета напрямую. Он этого не делает: ответ приходит в
        фоновую `_listen_loop`, которая раздаёт его обработчикам из `_handlers`.
        Из-за этого подмена `recv` не влияла ни на что, тесты выжидали полный
        таймаут, а второй был вдобавок пустым по смыслу.

        Тест запускает listen loop **без** ответа сервера и убеждается, что
        единственный путь к результату — `_handlers`. Если когда-нибудь клиент
        начнёт читать через `recv`, тест упадёт здесь, а не молча превратится в
        пустышку.

        Известный побочный дефект (не проверяется намеренно): по таймауту
        обработчик остаётся в `_handlers` — production-код его не снимает.
        """
        ws = FakeHAWebSocket()
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = ws
        client.connected = True
        client._listen_task = asyncio.create_task(client._listen_loop())

        real_wait_for = asyncio.wait_for

        async def shortened_wait_for(awaitable, timeout):
            return await real_wait_for(awaitable, timeout=0.01)

        try:
            with patch(
                "src.adapters.ha_adapter.asyncio.wait_for",
                new=shortened_wait_for,
            ):
                assert await client.get_states() == []
            # Ни одного прямого чтения сокета — только входящая очередь.
            assert ws.recv_calls == []
            assert ws.sent == [{"id": 1, "type": "get_states"}]
        finally:
            await client.close()

        assert ws.closed is True

    @pytest.mark.asyncio
    async def test_ws_client_close_cleans_up(self):
        """close() should cleanup listen task and connection."""
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )

        # Create a proper mock task that can be awaited
        async def dummy_coro():
            pass

        mock_task = asyncio.create_task(dummy_coro())
        mock_task.cancel = MagicMock()  # Override cancel to track calls
        client._listen_task = mock_task

        # Create a proper mock WebSocket
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        client.ws = mock_ws
        client.connected = True

        await client.close()

        mock_task.cancel.assert_called_once()
        mock_ws.close.assert_awaited_once()
        assert client.connected is False


class TestHAAdapterTraceCallbacks:
    """Test trace callback registration and invocation."""

    def test_register_trace_callback_adds_to_list(self):
        """register_trace_callback should add callback to internal list."""
        hass_mock = MagicMock()
        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        callback_mock = AsyncMock()
        adapter.register_trace_callback(callback_mock)

        assert len(adapter._trace_callbacks) == 1
        assert adapter._trace_callbacks[0] == callback_mock

    def test_register_multiple_trace_callbacks(self):
        """Multiple callbacks should be stored in order."""
        hass_mock = MagicMock()
        adapter = HAAdapter(mode="pyscript", engine=None, hass=hass_mock)

        callback1 = AsyncMock()
        callback2 = AsyncMock()

        adapter.register_trace_callback(callback1)
        adapter.register_trace_callback(callback2)

        assert len(adapter._trace_callbacks) == 2
        assert adapter._trace_callbacks == [callback1, callback2]


class TestHAAdapterIntegrationScenarios:
    """Integration scenarios testing complete workflows."""

    @pytest.mark.asyncio
    async def test_full_motion_detection_workflow(self):
        """Complete workflow: motion detected -> light turned on."""
        hass_mock = MagicMock()
        hass_mock.services.async_call = AsyncMock()

        engine_mock = MagicMock()
        engine_mock.event_bus = MagicMock()
        engine_mock.event_bus.publish = AsyncMock()

        adapter = HAAdapter(mode="pyscript", engine=engine_mock, hass=hass_mock)

        # Simulate motion detection
        await adapter.on_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={"trace_id": "motion123"},
        )

        # Verify event was published
        assert engine_mock.event_bus.publish.called

        # Simulate action triggering service call
        await adapter.call_service(
            domain="light",
            service="turn_on",
            entity_id="light.kitchen",
            data={"brightness": 255},
            trace_id="action123",
        )

        # Verify service was called
        hass_mock.services.async_call.assert_called_once()

    @pytest.mark.asyncio
    async def test_manual_override_lockout_workflow(self):
        """Workflow: manual control -> automated commands blocked."""
        hass_mock = MagicMock()
        middleware_mock = MagicMock()
        middleware_mock.record_manual_control = MagicMock()

        adapter = HAAdapter(
            mode="pyscript",
            engine=None,
            hass=hass_mock,
            manual_lockout_middleware=middleware_mock,
        )

        # User manually turns on light
        await adapter.on_state_change(
            entity_id="light.kitchen",
            new_state="on",
            old_state="off",
            context={"user_id": "user_123"},
        )

        # Verify manual control was recorded
        middleware_mock.record_manual_control.assert_called_once_with("light.kitchen")

    @pytest.mark.asyncio
    async def test_websocket_state_change_propagation(self):
        """WebSocket mode: incoming WS message -> state change event."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        event_router_mock = MagicMock()
        event_router_mock.route_state_change = AsyncMock()
        adapter._event_router = event_router_mock

        # Simulate WebSocket message handling
        message = {
            "entity_id": "binary_sensor.motion",
            "old_state": {"state": "off"},
            "new_state": {"state": "on"},
        }

        await adapter._handle_ws_state_change(message, trace_id="ws123")

        # Verify state change was processed
        event_router_mock.route_state_change.assert_called_once()
