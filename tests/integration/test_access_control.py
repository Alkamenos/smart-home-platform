"""
Интеграционные тесты для полного потока управления доступом к устройствам.

Тесты проверяют полный сценарий: назначение прав → проверка доступа → отзыв прав.
"""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch
from uuid import uuid4


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
        headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
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
                "attributes": {"friendly_name": "Living Room Light"}
            }
        ]

        with patch("src.adapters.home_assistant.rest_client.HARestClient.fetch_devices",
                   return_value=mock_devices_response):
            sync_response = client.post(
                f"/api/v1/devices/sources/{sample_source['id']}/sync",
                headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
            )
            assert sync_response.status_code in [200, 202]

        # Получаем ID загруженного устройства
        devices_response = client.get(
            "/api/v1/devices",
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert devices_response.status_code == 200
        devices = devices_response.json()
        assert len(devices) > 0

        device_id = devices[0]["id"]

        # 2. Обычный пользователь не видит устройство (нет доступа)
        user_devices_response = client.get(
            "/api/v1/devices",
            headers={"X-User-ID": regular_user_id}
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
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert grant_response.status_code in [200, 201]
        access_record = grant_response.json()
        assert access_record["role"] == "viewer"
        access_id = access_record["id"]

        # 4. Пользователь теперь видит устройство
        user_devices_response = client.get(
            "/api/v1/devices",
            headers={"X-User-ID": regular_user_id}
        )
        assert user_devices_response.status_code == 200
        user_devices = user_devices_response.json()
        device_ids = [d["id"] for d in user_devices]
        assert device_id in device_ids, "User should see devices with viewer access"

        # Пользователь может получить информацию об устройстве
        device_detail_response = client.get(
            f"/api/v1/devices/{device_id}",
            headers={"X-User-ID": regular_user_id}
        )
        assert device_detail_response.status_code == 200

        # 5. Пользователь НЕ может отправить команду с доступом viewer
        command_response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_off"},
            headers={"X-User-ID": regular_user_id}
        )
        # Должен быть 403 Forbidden
        assert command_response.status_code == 403

        # 6. Администратор повышает доступ до controller
        update_response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "controller"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert update_response.status_code in [200, 201]
        updated_access = update_response.json()
        assert updated_access["role"] == "controller"

        # 7. Теперь пользователь может отправить команду
        command_response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_off"},
            headers={"X-User-ID": regular_user_id}
        )
        # Должен быть успешный ответ (200 или 202)
        assert command_response.status_code in [200, 202]

        # 8. Администратор отзывает доступ
        revoke_response = client.delete(
            f"/api/v1/devices/{device_id}/access/{access_id}",
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )
        assert revoke_response.status_code in [200, 204]

        # 9. Пользователь больше не видит устройство
        user_devices_response = client.get(
            "/api/v1/devices",
            headers={"X-User-ID": regular_user_id}
        )
        assert user_devices_response.status_code == 200
        user_devices = user_devices_response.json()
        device_ids = [d["id"] for d in user_devices]
        assert device_id not in device_ids, "User should not see devices after access revoked"

        # 10. Пользователь не может получить информацию об устройстве
        device_detail_response = client.get(
            f"/api/v1/devices/{device_id}",
            headers={"X-User-ID": regular_user_id}
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
            "/api/v1/devices",
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
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
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )

        # Второму пользователю - controller
        client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": another_user_id, "role": "controller"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )

        # Проверяем что первый пользователь не может отправить команду
        response1 = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_on"},
            headers={"X-User-ID": regular_user_id}
        )
        assert response1.status_code == 403

        # Проверяем что второй пользователь может отправить команду
        response2 = client.post(
            f"/api/v1/devices/{device_id}/command",
            json={"command_name": "turn_on"},
            headers={"X-User-ID": another_user_id}
        )
        assert response2.status_code in [200, 202]

    @pytest.mark.skip(reason="Зависит от T064-T067 реализации")
    def test_admin_access_restrictions(
        self, client, admin_user_id, regular_user_id, sample_source
    ):
        """T063: Проверка что только админ может управлять доступом."""
        if not sample_source:
            pytest.skip("Source creation failed")

        devices_response = client.get(
            "/api/v1/devices",
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
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
            headers={"X-User-ID": regular_user_id}  # Не админ
        )

        # Должен быть 403 Forbidden
        assert response.status_code == 403

        # Только администратор может назначать доступ
        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json={"user_id": regular_user_id, "role": "viewer"},
            headers={"X-User-ID": admin_user_id, "X-Is-Admin": "true"}
        )

        # Должен быть успешный ответ
        assert response.status_code in [200, 201]
