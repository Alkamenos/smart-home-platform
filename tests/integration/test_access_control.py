"""
Интеграционные тесты для полного потока управления доступом к устройствам.

Тесты проверяют полный сценарий: назначение прав → проверка доступа → отзыв прав.
"""

from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.fixture
def admin_user_id():
    """ID администратора."""
    return str(uuid4())


@pytest.fixture
def regular_user_id():
    """ID обычного пользователя."""
    return str(uuid4())


@pytest.fixture
def another_user_id():
    """ID еще одного пользователя для тестов."""
    return str(uuid4())


@pytest.fixture
def sample_source(client, admin_user_id):
    """Создает тестовый источник."""
    payload = {
        "name": "Integration Test Access Control Source",
        "url": "http://192.168.1.100:8123",
        "token": "integration_access_control_token",
    }
    response = client.post(
        "/api/v1/devices/sources",
        json=payload,
        headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
    )
    return response.json() if response.status_code == 201 else None


class TestAccessControlIntegration:
    """Интеграционные тесты для управления доступом."""

    @pytest.mark.skip(reason="Зависит от T064-T067 реализации")
    def test_full_access_control_flow(
        self, client, admin_user_id, regular_user_id, another_user_id, sample_source
    ):
        """T063: Полный поток управления доступом.

        Сценарий:
        1. Администратор создает источник и загружает устройства
        2. По умолчанию обычные пользователи не видят новые устройства
        3. Администратор назначает доступ пользователю (viewer)
        4. Пользователь может видеть устройство, но не может управлять
        5. Администратор повышает доступ до controller
        6. Пользователь может отправлять команды
        7. Администратор отзывает доступ
        8. Пользователь больше не видит устройство
        """
        if not sample_source:
            pytest.skip("Source creation failed")

        # 1. Администратор загружает устройства (в реальности это будет через синхронизацию)
        # Для теста используем мок
        mock_devices_response = [
            {
                "entity_id": "light.living_room",
                "state": "on",
                "attributes": {"friendly_name": "Living Room Light"},
            }
        ]

        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient.fetch_devices",
            return_value=mock_devices_response,
        ):
            sync_response = client.post(
                f"/api/v1/devices/sources/{sample_source['id']}/sync",
                headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
            )
            assert sync_response.status_code in [200, 202]

        # Получаем ID загруженного устройства
        devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert devices_response.status_code == 200
        devices = devices_response.json()
        assert len(devices) > 0

        device_id = devices[0]["id"]

        # 2. Обычный пользователь не видит устройство (нет доступа)
        user_devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": regular_user_id}
        )
        assert user_devices_response.status_code == 200
        user_devices = user_devices_response.json()
        # Пользователь не должен видеть устройства, к которым нет доступа
        device_ids = [d["id"] for d in user_devices]
        assert device_id not in device_ids, "User should not see devices without access"

        # 3. Администратор назначает доступ viewer
        grant_response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "viewer"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )
        assert grant_response.status_code in [200, 201]
        access_record = grant_response.json()
        assert access_record["role"] == "viewer"
        access_id = access_record["id"]

        # 4. Пользователь теперь видит устройство
        user_devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": regular_user_id}
        )
        assert user_devices_response.status_code == 200
        user_devices = user_devices_response.json()
        device_ids = [d["id"] for d in user_devices]
        assert device_id in device_ids, "User should see devices with viewer access"

        # Пользователь может получить информацию об устройстве
        device_detail_response = client.get(
            f"/api/v1/devices/{device_id}", headers={"X-User-ID": regular_user_id}
        )
        assert device_detail_response.status_code == 200

        # 5. Пользователь НЕ может отправить команду с доступом viewer
        command_response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_off"},
            headers={"X-User-ID": regular_user_id},
        )
        # Должен быть 403 Forbidden
        assert command_response.status_code == 403

        # 6. Администратор повышает доступ до controller
        update_response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "controller"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )
        assert update_response.status_code in [200, 201]
        updated_access = update_response.json()
        assert updated_access["role"] == "controller"

        # 7. Теперь пользователь может отправить команду
        command_response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_off"},
            headers={"X-User-ID": regular_user_id},
        )
        # Должен быть успешный ответ (200 или 202)
        assert command_response.status_code in [200, 202]

        # 8. Администратор отзывает доступ
        revoke_response = client.delete(
            f"/api/v1/devices/{device_id}/access/{access_id}",
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )
        assert revoke_response.status_code in [200, 204]

        # 9. Пользователь больше не видит устройство
        user_devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": regular_user_id}
        )
        assert user_devices_response.status_code == 200
        user_devices = user_devices_response.json()
        device_ids = [d["id"] for d in user_devices]
        assert device_id not in device_ids, "User should not see devices after access revoked"

        # 10. Пользователь не может получить информацию об устройстве
        device_detail_response = client.get(
            f"/api/v1/devices/{device_id}", headers={"X-User-ID": regular_user_id}
        )
        # Должен быть 403 или 404
        assert device_detail_response.status_code in [403, 404]

    @pytest.mark.skip(reason="Зависит от T064-T067 реализации")
    def test_multiple_users_access(
        self, client, admin_user_id, regular_user_id, another_user_id, sample_source
    ):
        """T063: Проверка управления доступом для нескольких пользователей."""
        if not sample_source:
            pytest.skip("Source creation failed")

        # Загружаем устройство
        devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert devices_response.status_code == 200
        devices = devices_response.json()

        if not devices:
            pytest.skip("No devices available")

        device_id = devices[0]["id"]

        # Предоставляем разный доступ разным пользователям
        # Первому пользователю - viewer
        client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "viewer"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )

        # Второму пользователю - controller
        client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": another_user_id, "role": "controller"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )

        # Проверяем что первый пользователь не может отправить команду
        response1 = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_on"},
            headers={"X-User-ID": regular_user_id},
        )
        assert response1.status_code == 403

        # Проверяем что второй пользователь может отправить команду
        response2 = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_on"},
            headers={"X-User-ID": another_user_id},
        )
        assert response2.status_code in [200, 202]

    @pytest.mark.skip(reason="Зависит от T064-T067 реализации")
    def test_admin_access_restrictions(self, client, admin_user_id, regular_user_id, sample_source):
        """T063: Проверка что только админ может управлять доступом."""
        if not sample_source:
            pytest.skip("Source creation failed")

        devices_response = client.get(
            "/api/v1/devices", headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert devices_response.status_code == 200
        devices = devices_response.json()

        if not devices:
            pytest.skip("No devices available")

        device_id = devices[0]["id"]

        # Обычный пользователь пытается назначить доступ
        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "viewer"},
            headers={"X-User-ID": regular_user_id},  # Не админ
        )

        # Должен быть 403 Forbidden
        assert response.status_code == 403

        # Только администратор может назначать доступ
        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "viewer"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть успешный ответ
        assert response.status_code in [200, 201]


class TestDeviceEventDeliveryRights:
    """Spec 004 US3: доставка событий WS по правам (проверка при каждой доставке)."""

    def test_device_event_delivery_revoked_after_revoke(self, admin_user_id, regular_user_id):
        """T014: подписка с доступом → событие доставлено; после отзыва → не доставлено."""
        from src.main import app

        device_id = str(uuid4())
        headers = {"X-User-ID": admin_user_id, "X-Is-Admin": "true"}

        with TestClient(app) as client:
            # Выдаём viewer-доступ обычному пользователю (grant до синка — device-blind)
            grant = client.post(
                f"/api/v1/devices/{device_id}/access",
                json={"user_id": regular_user_id, "role": "viewer"},
                headers=headers,
            )
            assert grant.status_code in [200, 201]

            # ВАЖНО: импорт из того же модуля, который использует приложение
            # (main.py импортирует top-level `webui`, а не `src.webui` —
            # разные имена = разные экземпляры connection_manager)
            from webui.routes.devices.websocket import broadcast_state_change

            with client.websocket_connect("/api/v1/ws/devices") as ws:
                ws.send_json({"type": "auth", "user_id": regular_user_id})
                auth_reply = ws.receive_json()
                assert auth_reply["type"] == "authenticated"

                ws.send_json({"type": "subscribe", "device_id": device_id})
                sub_reply = ws.receive_json()
                assert sub_reply["type"] == "subscribed"

                # Событие доставлено (доступ есть) — broadcast в портале TestClient
                client.portal.call(broadcast_state_change, device_id, {"state": "on"})
                delivered = ws.receive_json()
                assert delivered["type"] == "state_changed"
                assert delivered["device_id"] == device_id

            # Отзываем доступ
            access_id = grant.json()["id"]
            revoke = client.delete(
                f"/api/v1/devices/{device_id}/access/{access_id}", headers=headers
            )
            assert revoke.status_code in [200, 204]

            # Новое соединение (прошлая закрыта context manager'ом)
            with client.websocket_connect("/api/v1/ws/devices") as ws:
                ws.send_json({"type": "auth", "user_id": regular_user_id})
                ws.receive_json()

                ws.send_json({"type": "subscribe", "device_id": device_id})
                sub_reply = ws.receive_json()
                # Доступ отозван — подписка отклоняется
                assert sub_reply["type"] == "error", f"ожидался error: {sub_reply}"


class TestAccessPersistenceAcrossRestarts:
    """Spec 004 US2: доступы переживают перезапуск (FR-010, SC-004)."""

    def test_access_survives_service_restart(self, admin_user_id, regular_user_id):
        """T019: grant → пересоздать DeviceService → доступ сохранился."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.persistence.manager import PersistenceManager
        from src.services.device_service import DeviceService

        device_id = uuid4()

        async def flow():
            svc = DeviceService(
                event_bus=EventBus(),
                persistence_module=PersistenceManager(data_dir="data"),
                ha_adapter=None,
            )
            grant = await svc.grant_access(
                device_id=device_id,
                user_id=regular_user_id,
                role="controller",
                granted_by=admin_user_id,
            )
            assert grant is not None, "grant должен создаться"

            # «Перезапуск»: новый экземпляр сервиса с той же персистентностью
            restarted = DeviceService(
                event_bus=EventBus(),
                persistence_module=PersistenceManager(data_dir="data"),
                ha_adapter=None,
            )
            accesses = await restarted.get_device_accesses(device_id)
            return [a for a in accesses if a.user_id == regular_user_id], restarted, device_id

        import asyncio

        records, restarted_svc, dev_id = asyncio.run(flow())

        assert len(records) == 1, f"ожидалась 1 запись после перезапуска: {records}"
        assert records[0].role == "controller"

        # Проверка доступа через перезапущенный сервис
        ok = asyncio.run(
            restarted_svc.check_device_access(UUID(str(dev_id)), regular_user_id, "viewer")
        )
        assert ok is True

        # Убираем за собой
        asyncio.run(restarted_svc.revoke_access(records[0].id))
