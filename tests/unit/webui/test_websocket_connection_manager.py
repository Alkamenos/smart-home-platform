"""
Тесты менеджера WebSocket-соединений устройств.

Менеджер отвечает за разграничение доступа при доставке: подписчику без прав
событие не отправляется, а отключившиеся соединения отключаются (FR-025).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from src.webui.routes.devices.websocket import WebSocketConnectionManager


@pytest.fixture
def manager() -> WebSocketConnectionManager:
    """Менеджер без соединений."""
    return WebSocketConnectionManager()


def make_socket(**kwargs: object) -> MagicMock:
    """Создать сокет для теста.

    Args:
        **kwargs: Значения для ``scope`` сокета.

    Returns:
        Объект с поведением WebSocket.
    """
    socket = MagicMock()
    socket.accept = AsyncMock()
    socket.send_json = AsyncMock()
    socket.scope = kwargs.get("scope", {})
    return socket


class TestConnectionLifecycle:
    """Подключение и отключение (FR-012)."""

    async def test_should_add_connection_when_connected(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Подключение попадает в список активных."""
        socket = make_socket()

        await manager.connect(socket)

        assert socket in manager.active_connections

    def test_should_remove_connection_when_disconnected(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Отключение убирает соединение и его идентификацию."""
        socket = make_socket()
        manager.active_connections.append(socket)
        manager.register_identity(socket, "user-1")

        manager.disconnect(socket)

        assert socket not in manager.active_connections
        assert manager.is_authenticated(socket) is False

    def test_should_not_raise_when_disconnecting_unknown_connection(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Отключение неизвестного соединения безопасно."""
        manager.disconnect(make_socket())


class TestIdentityAndSubscriptions:
    """Идентификация и подписки (FR-039)."""

    def test_should_register_identity_when_authenticated(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Аутентифицированное соединение опознаётся."""
        socket = make_socket()

        manager.register_identity(socket, "user-1")

        assert manager.is_authenticated(socket) is True

    def test_should_report_unauthenticated_without_identity(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Без аутентификации соединение анонимно."""
        assert manager.is_authenticated(make_socket()) is False

    def test_should_track_subscription_when_added(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Подписка на устройство фиксируется."""
        socket = make_socket()

        manager.add_subscription(socket, "device-1")

        assert manager.is_subscribed(socket, "device-1") is True
        assert manager.is_subscribed(socket, "device-2") is False

    def test_should_drop_subscription_when_removed(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Отписка убирает устройство."""
        socket = make_socket()
        manager.add_subscription(socket, "device-1")

        manager.remove_subscription(socket, "device-1")

        assert manager.is_subscribed(socket, "device-1") is False

    def test_should_not_raise_when_removing_unknown_subscription(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Отписка от неизвестного устройства безопасна."""
        manager.remove_subscription(make_socket(), "device-1")


class TestAccessCheck:
    """Проверка доступа при доставке (FR-025)."""

    async def test_should_deny_when_application_absent(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Нет приложения — безопасный отказ."""
        assert await manager._has_access_now(make_socket(), "device-1", "user-1") is False

    async def test_should_deny_when_service_absent(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Нет сервиса устройств — безопасный отказ."""
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=None))})

        assert await manager._has_access_now(socket, "device-1", "user-1") is False

    async def test_should_allow_when_service_grants_access(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Сервис разрешил доступ — событие доставляется."""
        from uuid import uuid4

        service = MagicMock()
        service.check_device_access = AsyncMock(return_value=True)
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=service))})
        device_id = str(uuid4())

        assert await manager._has_access_now(socket, device_id, "user-1") is True

    async def test_should_deny_when_access_check_raises(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Ошибка проверки доступа трактуется как отказ."""
        from uuid import uuid4

        service = MagicMock()
        service.check_device_access = AsyncMock(side_effect=RuntimeError("db down"))
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=service))})

        assert await manager._has_access_now(socket, str(uuid4()), "user-1") is False

    async def test_should_deny_for_invalid_device_id(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Неидентификатор устройства не приводит к исключению."""
        service = MagicMock()
        service.check_device_access = AsyncMock(return_value=True)
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=service))})

        assert await manager._has_access_now(socket, "not-a-uuid", "user-1") is False


class TestBroadcastToDevice:
    """Рассылка событий устройства (FR-025)."""

    async def test_should_send_to_subscribed_with_access(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Подписчик с доступом получает событие."""
        from uuid import uuid4

        device_id = str(uuid4())
        service = MagicMock()
        service.check_device_access = AsyncMock(return_value=True)
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=service))})
        await manager.connect(socket)
        manager.register_identity(socket, "user-1")
        manager.add_subscription(socket, device_id)

        await manager.broadcast_device_event(device_id, {"type": "fsm_transition"})

        socket.send_json.assert_awaited_once_with({"type": "fsm_transition"})

    async def test_should_skip_connection_without_subscription(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Подписки нет — событие не отправляется."""
        from uuid import uuid4

        socket = make_socket()
        await manager.connect(socket)
        manager.register_identity(socket, "user-1")

        await manager.broadcast_device_event(str(uuid4()), {"type": "fsm_transition"})

        socket.send_json.assert_not_awaited()

    async def test_should_skip_connection_without_identity(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Анонимное соединение не получает событий."""
        from uuid import uuid4

        device_id = str(uuid4())
        socket = make_socket()
        await manager.connect(socket)
        manager.add_subscription(socket, device_id)

        await manager.broadcast_device_event(device_id, {"type": "fsm_transition"})

        socket.send_json.assert_not_awaited()

    async def test_should_disconnect_failing_connection(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Соединение, на которое не удалось отправить, отключается."""
        from uuid import uuid4

        device_id = str(uuid4())
        service = MagicMock()
        service.check_device_access = AsyncMock(return_value=True)
        socket = make_socket(scope={"app": MagicMock(state=MagicMock(device_service=service))})
        socket.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        await manager.connect(socket)
        manager.register_identity(socket, "user-1")
        manager.add_subscription(socket, device_id)

        await manager.broadcast_device_event(device_id, {"type": "fsm_transition"})

        assert socket not in manager.active_connections


class TestBroadcastAllAndPersonal:
    """Общая рассылка и личное сообщение."""

    async def test_should_send_to_every_connection(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Общая рассылка доходит до всех соединений."""
        first, second = make_socket(), make_socket()
        await manager.connect(first)
        await manager.connect(second)

        await manager.broadcast({"type": "ping"})

        first.send_json.assert_awaited_once()
        second.send_json.assert_awaited_once()

    async def test_should_disconnect_failing_connection_on_broadcast(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Упавшее соединение отключается после общей рассылки."""
        broken = make_socket()
        broken.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        await manager.connect(broken)

        await manager.broadcast({"type": "ping"})

        assert broken not in manager.active_connections

    async def test_should_send_personal_message(self, manager: WebSocketConnectionManager) -> None:
        """Личное сообщение отправляется конкретному соединению."""
        socket = make_socket()

        await manager.send_personal(socket, {"type": "pong"})

        socket.send_json.assert_awaited_once_with({"type": "pong"})

    async def test_should_not_raise_when_personal_send_fails(
        self, manager: WebSocketConnectionManager
    ) -> None:
        """Ошибка личной отправки не поднимается."""
        socket = make_socket()
        socket.send_json = AsyncMock(side_effect=RuntimeError("closed"))

        await manager.send_personal(socket, {"type": "pong"})
