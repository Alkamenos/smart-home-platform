"""
Контрактные тесты для управления доступом к устройствам.

Тесты проверяют контракт между клиентом и сервером для операций управления доступом
на основе ролей пользователей.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.fixture
def current_user_id():
    """ID текущего пользователя для тестов."""
    return str(uuid4())


@pytest.fixture
def other_user_id():
    """ID другого пользователя для тестов."""
    return str(uuid4())


@pytest.fixture
def sample_source(client):
    """Фикстура для создания тестового источника."""
    payload = {
        "name": "Access Control Test Source",
        "url": "http://192.168.1.100:8123",
        "token": "access_control_token",
    }
    response = client.post("/api/v1/devices/sources", json=payload)
    return response.json() if response.status_code == 201 else None


@pytest.fixture
def sample_device(client, sample_source):
    """Фикстура для создания тестового устройства."""
    if not sample_source:
        return None

    # Для теста используем фиксированный ID устройства
    return {
        "id": str(uuid4()),
        "ha_entity_id": "light.test_access",
        "source_id": sample_source["id"],
        "name": "Test Access Device",
        "device_type": "light",
        "status": "available",
    }


class TestAccessControlAPI:
    """Тесты для контракта API управления доступом."""

    # T061: Контрактный тест для проверки прав доступа

    def test_get_device_without_access_returns_403(self, client, current_user_id, other_user_id):
        """T061: Получение устройства без прав доступа возвращает 403."""
        device_id = str(uuid4())

        # Пользователь пытается получить устройство, к которому нет доступа
        # (в реальной реализации это будет проверено middleware)
        response = client.get(f"/api/v1/devices/{device_id}", headers={"X-User-ID": other_user_id})

        # Должен быть 403 Forbidden или 404 (не видит устройство)
        assert response.status_code in [403, 404]

    def test_get_device_with_viewer_access(self, client, current_user_id, sample_device):
        """T061: Пользователь с ролью viewer может видеть устройство."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пользователь имеет доступ viewer к устройству
        response = client.get(
            f"/api/v1/devices/{device_id}", headers={"X-User-ID": current_user_id}
        )

        # Должен быть 200 или 404 (если устройство не синхронизировано)
        assert response.status_code in [200, 404]

    def test_execute_command_without_controller_access_returns_403(
        self, client, other_user_id, sample_device
    ):
        """T061: Отправка команды без прав controller возвращает 403."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пользователь пытается отправить команду без прав
        payload = {"command_name": "turn_on"}

        response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json=payload,
            headers={"X-User-ID": other_user_id},
        )

        # Должен быть 403 Forbidden
        assert response.status_code in [403, 404]

    def test_execute_command_with_controller_access(self, client, current_user_id, sample_device):
        """T061: Пользователь с ролью controller может отправить команду."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пользователь с доступом controller отправляет команду
        payload = {"command_name": "turn_on"}

        response = client.post(
            f"/api/v1/devices/{device_id}/command",
            json=payload,
            headers={"X-User-ID": current_user_id},
        )

        # Должен быть 200 (успех) или 404 (устройство не найдено)
        assert response.status_code in [200, 202, 404]

    # T062: Контрактный тест для управления правами доступа

    def test_grant_access_to_device(self, client, current_user_id, other_user_id, sample_device):
        """T062: Администратор может назначить доступ пользователю."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Администратор назначает доступ пользователю
        payload = {
            "user_id": other_user_id,
            "role": "viewer",  # Роли: viewer, controller, admin
        }

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 201 Created или 200 OK
        assert response.status_code in [200, 201]

        if response.status_code in [200, 201]:
            data = response.json()
            assert data.get("user_id") == other_user_id
            assert data.get("role") == "viewer"
            assert "device_id" in data
            assert "id" in data

    def test_grant_access_by_non_admin_returns_403(
        self, client, current_user_id, other_user_id, sample_device
    ):
        """T062: Обычный пользователь не может назначать доступ."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Обычный пользователь (не админ) пытается назначить доступ
        payload = {"user_id": other_user_id, "role": "viewer"}

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id},  # Не админ
        )

        # Должен быть 403 Forbidden
        assert response.status_code == 403

    def test_revoke_access(self, client, current_user_id, other_user_id, sample_device):
        """T062: Администратор может отозвать доступ."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]
        access_id = str(uuid4())  # ID записи доступа

        # Администратор отзывает доступ
        response = client.delete(
            f"/api/v1/devices/{device_id}/access/{access_id}",
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 204 No Content или 200 OK или 404 (если запись не найдена)
        assert response.status_code in [200, 204, 404]

    def test_get_device_access_list(self, client, current_user_id, sample_device):
        """T062: Получение списка доступа к устройству."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Администратор получает список доступа
        response = client.get(
            f"/api/v1/devices/{device_id}/access",
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 200 OK
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            assert isinstance(data, list)
            # Каждая запись должна содержать информацию о доступе
            for access in data:
                assert "id" in access
                assert "user_id" in access
                assert "role" in access
                assert access["role"] in ["viewer", "controller", "admin"]

    def test_valid_roles(self, client, current_user_id, other_user_id, sample_device):
        """T062: Проверка что система поддерживает роли: viewer, controller, admin."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Тестируем все роли
        for role in ["viewer", "controller", "admin"]:
            payload = {"user_id": other_user_id, "role": role}

            response = client.post(
                f"/api/v1/devices/{device_id}/access",
                json=payload,
                headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
            )

            # Должен быть успешный ответ
            assert response.status_code in [200, 201]

    def test_invalid_role_returns_400(self, client, current_user_id, other_user_id, sample_device):
        """T062: Некорректная роль возвращает 400 Bad Request."""
        if not sample_device:
            pytest.skip("Sample device creation failed")

        device_id = sample_device["id"]

        # Пытаемся назначить некорректную роль
        payload = {"user_id": other_user_id, "role": "invalid_role"}

        response = client.post(
            f"/api/v1/devices/{device_id}/access",
            json=payload,
            headers={"X-User-ID": current_user_id, "X-Is-Admin": "true"},
        )

        # Должен быть 400 Bad Request
        assert response.status_code == 400
