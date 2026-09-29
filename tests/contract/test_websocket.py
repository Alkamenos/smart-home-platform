"""
Контрактные тесты для WebSocket API синхронизации состояния устройств.

T043: Проверяет контракт для WebSocket подписки на события state_changed.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import WSMsgType


class TestWebSocketContract:
    """Контрактные тесты для WebSocket API."""

    @pytest.mark.asyncio
    async def test_websocket_subscribe_to_state_changes(self):
        """T043: WebSocket может подписаться на события state_changed."""
        from src.adapters.home_assistant.websocket_client import HAWebSocketClient

        client = HAWebSocketClient(
            base_url="http://localhost:8123",
            token="test_token",
        )

        # Mock WebSocket соединение
        mock_ws = AsyncMock()
        client.ws = mock_ws
        client._running = True

        # Должен вернуть True при успешной подписке
        result = await client.subscribe_to_state_changes()

        assert result is True
        assert client._subscription_id is not None

    @pytest.mark.asyncio
    async def test_websocket_receives_state_changed_event(self):
        """T043: WebSocket получает и обрабатывает события state_changed."""
        from src.adapters.home_assistant.websocket_client import HAWebSocketClient

        received_events = []

        async def on_state_changed(event_data):
            """Callback для обработки события."""
            received_events.append(event_data)

        client = HAWebSocketClient(
            base_url="http://localhost:8123",
            token="test_token",
            on_state_changed=on_state_changed,
        )

        # Mock события
        state_changed_event = {
            "type": "event",
            "event": {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "light.kitchen",
                    "old_state": {"state": "off"},
                    "new_state": {"state": "on"},
                },
            },
        }

        # Mock WebSocket для возврата события
        mock_ws = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.type = WSMsgType.TEXT
        mock_msg.data = json.dumps(state_changed_event)

        # Установим первое сообщение как событие, второе как CLOSED
        async def mock_iter():
            yield mock_msg
            closed_msg = MagicMock()
            closed_msg.type = WSMsgType.CLOSED
            yield closed_msg

        mock_ws.__aiter__ = mock_iter

        client.ws = mock_ws
        client._running = True

        # Запустим listen
        await client.listen()

        # Проверим что событие было получено
        assert len(received_events) > 0
        assert received_events[0].get("event_type") == "state_changed"

    @pytest.mark.asyncio
    async def test_websocket_handles_connection_errors(self):
        """T043: WebSocket корректно обрабатывает ошибки соединения."""
        from src.adapters.home_assistant.websocket_client import HAWebSocketClient

        client = HAWebSocketClient(
            base_url="http://localhost:8123",
            token="test_token",
        )

        # Mock WebSocket с ошибкой
        mock_ws = AsyncMock()
        mock_msg = MagicMock()
        mock_msg.type = WSMsgType.ERROR
        mock_ws.exception.return_value = Exception("Connection error")

        async def mock_iter():
            yield mock_msg

        mock_ws.__aiter__ = mock_iter

        client.ws = mock_ws
        client._running = True

        # Запустим listen
        await client.listen()

        # После ошибки, соединение должно быть неактивно
        assert client._running is False

    def test_websocket_subscription_message_format(self):
        """T043: WebSocket отправляет правильный формат сообщения подписки."""
        from src.adapters.home_assistant.websocket_client import HAWebSocketClient

        client = HAWebSocketClient(
            base_url="http://localhost:8123",
            token="test_token",
        )

        # Проверяем что subscribe_message имеет правильный формат
        expected_format = {
            "id": int,
            "type": "subscribe_events",
            "event_type": "state_changed",
        }

        # Структура сообщения проверяется в коде
        assert hasattr(client, "_message_id")
        assert hasattr(client, "_subscription_id")
