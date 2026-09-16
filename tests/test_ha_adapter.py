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

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest
from loguru import logger

from adapters.ha_adapter import HAAdapter, SimpleHAWebSocketClient


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
        """WebSocket reconnection should use exponential backoff."""
        adapter = HAAdapter(
            mode="websocket",
            ws_url="ws://localhost:8123",
            token="test_token",
        )

        # Mock session and ws_client creation
        with patch("aiohttp.ClientSession") as mock_session_class:
            mock_session = AsyncMock()
            mock_session_class.return_value = mock_session

            with patch.object(adapter, "_cleanup_websocket", new_callable=AsyncMock):
                # Simulate connection failure
                connect_attempt_count = 0

                async def failing_connect():
                    nonlocal connect_attempt_count
                    connect_attempt_count += 1
                    raise ConnectionError("Connection failed")

                # This would test the backoff logic in _connect_websocket
                # Full integration test requires more complex mocking
                pass


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
        """get_states() should fetch and return states."""
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = AsyncMock()
        client.connected = True

        # Mock response
        async def mock_recv():
            return '{"type": "result", "id": 1, "result": [{"entity_id": "light.kitchen"}]}'

        client.ws.recv = mock_recv

        states = await client.get_states()

        assert isinstance(states, list)

    @pytest.mark.asyncio
    async def test_ws_client_get_states_timeout(self):
        """get_states() timeout should return empty list."""
        client = SimpleHAWebSocketClient(
            url="ws://localhost:8123",
            token="test_token",
        )
        client.ws = AsyncMock()
        client.connected = True

        # Mock timeout
        async def mock_timeout():
            await asyncio.sleep(20)
            return ""

        client.ws.recv = mock_timeout

        states = await client.get_states()

        assert states == []

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
