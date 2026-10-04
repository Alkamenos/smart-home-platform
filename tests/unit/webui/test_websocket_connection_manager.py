"""
Тесты менеджера WebSocket-соединений устройств.

Менеджер отвечает за разграничение доступа при доставке: подписчику без прав
событие не отправляется, а отключившиеся соединения отключаются (FR-025).
"""

from unittest.mock import AsyncMock, MagicMock, patch

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
        """Отключение неизвестного соединения не меняет реестр."""
        known = make_socket()
        manager.active_connections.append(known)
        manager.register_identity(known, "user-1")
        identities_before = dict(manager._identities)  # noqa: SLF001
        unknown = make_socket()

        manager.disconnect(unknown)

        # Реестр ровно прежний: чужое не удалено, лишнее не добавлено
        assert manager.active_connections == [known]
        assert unknown not in manager.active_connections
        assert manager._identities == identities_before  # noqa: SLF001
        # Известное соединение осталось аутентифицированным и рабочим
        assert manager.is_authenticated(known) is True


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
        """Отписка от неизвестного устройства безопасна и не портит подписки."""
        socket = make_socket()
        manager.register_identity(socket, "user-1")
        manager.add_subscription(socket, "device-1")
        # Подписка, попавшая в реестр помимо add_subscription (например, восстановленная)
        manager._identities[socket]["devices"].add("device-legacy")  # noqa: SLF001
        unknown = make_socket()

        manager.remove_subscription(socket, "device-2")
        manager.remove_subscription(socket, "device-legacy")
        manager.remove_subscription(unknown, "device-1")

        assert manager.is_subscribed(socket, "device-2") is False
        # Подписка из реестра убрана, своя не тронута
        assert manager.is_subscribed(socket, "device-legacy") is False
        assert manager.is_subscribed(socket, "device-1") is True
        # Неизвестное соединение не получает запись об идентичности
        assert unknown not in manager._identities  # noqa: SLF001
        assert set(manager._identities) == {socket}  # noqa: SLF001


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
        """Сбой личной отправки не отключает клиента и не мешает доставке остальным."""
        broken = make_socket()
        broken.send_json = AsyncMock(side_effect=RuntimeError("closed"))
        healthy = make_socket()
        await manager.connect(broken)
        await manager.connect(healthy)

        with patch("src.webui.routes.devices.websocket.logger") as mock_logger:
            await manager.send_personal(broken, {"type": "pong"})

            assert mock_logger.error.call_count == 1

        # Отправка была предпринята и сбой проглочен, а не передан вызывающему
        broken.send_json.assert_awaited_once_with({"type": "pong"})
        # В отличие от broadcast, личная отправка реестр не чистит
        assert manager.active_connections == [broken, healthy]
        # Сбой одного получателя не мешает общей рассылке остальным
        await manager.broadcast({"type": "ping"})

        healthy.send_json.assert_awaited_once_with({"type": "ping"})
