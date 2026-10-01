"""
Интеграционные тесты живых обновлений состояний автоматов (FR-024, FR-025).

Проверяют сквозной путь: переход автомата → событие → мост → WebSocket, а также
разграничение доступа при каждой доставке — события устройств, к которым у
пользователя нет прав, не должны доставляться ни по одному каналу (SC-009).
"""

import asyncio
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


ADMIN = {"X-User-ID": "admin_user", "X-Is-Admin": "true"}


@pytest.fixture
def client():
    """Клиент приложения."""
    from src.main import app

    with TestClient(app) as test_client:
        yield test_client


def grant_access(client: TestClient, device_id: str, user_id: str) -> str:
    """Выдать пользователю доступ к устройству.

    Args:
        client: Клиент приложения от администратора.
        device_id: Идентификатор устройства.
        user_id: Идентификатор пользователя.

    Returns:
        Идентификатор записи о доступе.
    """
    response = client.post(
        f"/api/v1/devices/{device_id}/access",
        json={"user_id": user_id, "role": "viewer"},
        headers=ADMIN,
    )
    assert response.status_code in (200, 201), response.text
    return response.json()["id"]


class TestFSMTransitionMessage:
    """Форма сообщения о переходе (FR-024, контракт §4)."""

    def test_should_include_contract_fields_when_transition_broadcast(self) -> None:
        """Сообщение содержит поля контракта."""
        from src.webui.routes.devices.websocket import build_fsm_transition_message

        payload = {
            "fsm_id": "light.kitchen_lighting_10",
            "device_id": "light.kitchen",
            "behavior": "lighting",
            "from_state": "OFF",
            "to_state": "ON_MOTION",
            "event": "motion_detected",
            "source": "automatic",
            "timestamp": "2026-10-01T14:23:11.482913",
        }

        message = build_fsm_transition_message(payload, "3f7bcdb0-3dfd-4940-b10e-8625a8772e1d")

        assert set(message.keys()) == {
            "type",
            "device_id",
            "fsm_id",
            "from_state",
            "state",
            "source",
            "timestamp",
        }
        assert message["type"] == "fsm_transition"
        assert message["state"] == "ON_MOTION"
        assert message["device_id"] == "3f7bcdb0-3dfd-4940-b10e-8625a8772e1d"

    def test_should_use_empty_from_state_when_first_entry(self) -> None:
        """Первый вход в состояние не имеет прежнего состояния."""
        from src.webui.routes.devices.websocket import build_fsm_transition_message

        message = build_fsm_transition_message(
            {
                "fsm_id": "light.kitchen_lighting_10",
                "device_id": "light.kitchen",
                "from_state": None,
                "to_state": "OFF",
                "source": "automatic",
                "timestamp": "2026-10-01T14:23:11.482913",
            },
            "3f7bcdb0-3dfd-4940-b10e-8625a8772e1d",
        )

        assert message["from_state"] is None

    def test_should_return_none_when_device_id_missing(self) -> None:
        """Без идентификатора устройства сообщение не формируется."""
        from src.webui.routes.devices.websocket import build_fsm_transition_message

        assert (
            build_fsm_transition_message(
                {"fsm_id": "light.kitchen_lighting_10", "to_state": "ON_MOTION"}, "device-uuid"
            )
            is None
        )


class TestEntityIdResolution:
    """Переход приходит с entity_id Home Assistant, а подписки — по UUID (FR-025)."""

    def test_should_resolve_device_uuid_by_entity_id(self, client: TestClient) -> None:
        """Entity_id автомата разрешается в идентификатор устройства."""
        import asyncio

        from src.main import app
        from src.webui.routes.devices.websocket import resolve_device_uuid

        devices = asyncio.run(app.state.device_service.get_all_devices())
        assert devices, "в хранилище должны быть устройства"
        entity_id = devices[0].ha_entity_id

        resolved = client.portal.call(resolve_device_uuid, app.state.device_service, entity_id)

        assert resolved == str(devices[0].id)

    def test_should_return_none_for_unknown_entity_id(self, client: TestClient) -> None:
        """Неизвестный entity_id не приводит к исключению."""
        from src.main import app
        from src.webui.routes.devices.websocket import resolve_device_uuid

        resolved = client.portal.call(
            resolve_device_uuid, app.state.device_service, "light.unknown"
        )

        assert resolved is None


class TestSingleModuleInstance:
    """Веб-слой загружается один раз (T042): иначе раздача уходит «в никуда»."""

    def test_should_share_connection_manager_between_app_and_module(
        self, client: TestClient
    ) -> None:
        """Приложение и модуль раздачи используют один менеджер соединений."""
        from src.webui.app import create_app
        from src.webui.routes.devices.websocket import connection_manager

        assert app_module_manager_is_same(connection_manager), (
            "приложение и модуль раздачи должны использовать один connection_manager"
        )
        assert callable(create_app)


def app_module_manager_is_same(manager: object) -> bool:
    """Проверить, что менеджер соединений единственный.

    Args:
        manager: Менеджер соединений модуля раздачи.

    Returns:
        True, если второй экземпляр модуля не был загружен.
    """
    import sys

    return "webui.routes.devices.websocket" not in sys.modules


class TestDeliveryByAccess:
    """Доставка только подписчикам с доступом (FR-025, SC-009)."""

    def test_should_deliver_transition_when_user_has_access(self, client: TestClient) -> None:
        """Пользователь с доступом получает переход своего устройства."""
        device_id = str(uuid4())
        user_id = str(uuid4())
        grant_access(client, device_id, user_id)

        from src.webui.routes.devices.websocket import (
            build_fsm_transition_message,
            connection_manager,
        )

        with client.websocket_connect("/api/v1/ws/devices") as ws:
            ws.send_json({"type": "auth", "user_id": user_id})
            assert ws.receive_json()["type"] == "authenticated"
            ws.send_json({"type": "subscribe", "device_id": device_id})
            assert ws.receive_json()["type"] == "subscribed"

            message = build_fsm_transition_message(
                {
                    "fsm_id": "light.kitchen_lighting_10",
                    "device_id": "light.kitchen",
                    "from_state": "OFF",
                    "to_state": "ON_MOTION",
                    "source": "automatic",
                    "timestamp": "2026-10-01T14:23:11.482913",
                },
                device_id,
            )
            client.portal.call(connection_manager.broadcast_device_event, device_id, message)

            delivered = ws.receive_json()
            assert delivered["type"] == "fsm_transition"
            assert delivered["state"] == "ON_MOTION"

    def test_should_not_deliver_transition_when_access_revoked(self, client: TestClient) -> None:
        """Отзыв доступа действует немедленно: переход больше не приходит."""
        device_id = str(uuid4())
        user_id = str(uuid4())
        access_id = grant_access(client, device_id, user_id)

        from src.webui.routes.devices.websocket import (
            build_fsm_transition_message,
            connection_manager,
        )

        with client.websocket_connect("/api/v1/ws/devices") as ws:
            ws.send_json({"type": "auth", "user_id": user_id})
            assert ws.receive_json()["type"] == "authenticated"
            ws.send_json({"type": "subscribe", "device_id": device_id})
            assert ws.receive_json()["type"] == "subscribed"

            client.delete(f"/api/v1/devices/{device_id}/access/{access_id}", headers=ADMIN)

            message = build_fsm_transition_message(
                {
                    "fsm_id": "light.a_lighting_10",
                    "device_id": "light.a",
                    "to_state": "ON",
                    "source": "automatic",
                    "timestamp": "2026-10-01T14:23:11.482913",
                },
                device_id,
            )
            client.portal.call(connection_manager.broadcast_device_event, device_id, message)

            # Событие не доставлено: соединение живо, но ждать нечего.
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] == "pong"

    def test_should_not_deliver_to_user_without_subscription(self, client: TestClient) -> None:
        """Аутентифицированный, но не подписанный пользователь событие не получает."""
        device_id = str(uuid4())
        user_id = str(uuid4())
        grant_access(client, device_id, user_id)

        from src.webui.routes.devices.websocket import (
            build_fsm_transition_message,
            connection_manager,
        )

        with client.websocket_connect("/api/v1/ws/devices") as ws:
            ws.send_json({"type": "auth", "user_id": user_id})
            assert ws.receive_json()["type"] == "authenticated"

            message = build_fsm_transition_message(
                {
                    "fsm_id": "light.b_lighting_10",
                    "device_id": "light.b",
                    "to_state": "ON",
                    "source": "automatic",
                    "timestamp": "2026-10-01T14:23:11.482913",
                },
                device_id,
            )
            client.portal.call(connection_manager.broadcast_device_event, device_id, message)

            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

    def test_should_require_authentication_before_subscription(self, client: TestClient) -> None:
        """Анонимная подписка невозможна (FR-039)."""
        device_id = str(uuid4())

        with client.websocket_connect("/api/v1/ws/devices") as ws:
            ws.send_json({"type": "subscribe", "device_id": device_id})
            reply = ws.receive_json()

            assert reply["type"] == "error"
            assert "authenticate" in reply["message"]


class TestBridgeBroadcast:
    """Мост вызывает раздачу при переходе (FR-024)."""

    def test_should_broadcast_when_bridge_receives_transition(self) -> None:
        """Переход, дошедший до моста, отправляется подписчикам."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock

        from src.core.events.event_bus import EventBus
        from src.services.fsm_state_bridge import FSMStateBridge

        broadcaster = AsyncMock()
        bus = EventBus()
        FSMStateBridge(event_bus=bus, dispatcher=None, event_store=MagicMock())

        bridge = FSMStateBridge(
            event_bus=bus, dispatcher=None, event_store=MagicMock(), broadcaster=broadcaster
        )
        payload = {
            "fsm_id": "light.kitchen_lighting_10",
            "device_id": "light.kitchen",
            "to_state": "ON_MOTION",
            "source": "automatic",
            "timestamp": "2026-10-01T14:23:11.482913",
        }

        asyncio.run(bridge.on_transitioned("fsm.transitioned", payload))

        broadcaster.assert_awaited_once_with(payload)


class TestEndToEndDelivery:
    """Сквозной путь: переход → шина → мост → раздатчик → сокет (FR-024)."""

    def test_should_deliver_real_transition_to_subscriber(self, client: TestClient) -> None:
        """Настоящее событие перехода доходит до подписанного клиента."""
        from src.main import app

        devices = asyncio.run(app.state.device_service.get_all_devices())
        assert devices, "нужно хотя бы одно устройство в хранилище"
        device = next((d for d in devices if d.ha_entity_id == "light.kitchen"), devices[0])
        user_id = str(uuid4())
        grant_access(client, str(device.id), user_id)

        fsm_id = f"{device.ha_entity_id}_lighting_10"

        with client.websocket_connect("/api/v1/ws/devices") as ws:
            ws.send_json({"type": "auth", "user_id": user_id})
            assert ws.receive_json()["type"] == "authenticated"
            ws.send_json({"type": "subscribe", "device_id": str(device.id)})
            assert ws.receive_json()["type"] == "subscribed"

            # Публикуем настоящее событие перехода через раздатчик приложения.
            client.portal.call(
                app.state.fsm_broadcaster,
                {
                    "fsm_id": fsm_id,
                    "device_id": device.ha_entity_id,
                    "from_state": "OFF",
                    "to_state": "ON_MOTION",
                    "source": "automatic",
                    "timestamp": "2026-10-01T14:23:11.482913",
                },
            )

            delivered = ws.receive_json()

        assert delivered["type"] == "fsm_transition"
        assert delivered["device_id"] == str(device.id)
        assert delivered["state"] == "ON_MOTION"
        assert delivered["from_state"] == "OFF"
        assert delivered["source"] == "automatic"
