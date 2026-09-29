"""
Контрактные тесты для API управления источниками Home Assistant.

Тесты проверяют контракт между клиентом и сервером для операций над источниками HA.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app  # Используем главное приложение

    return TestClient(app)


class TestSourcesAPI:
    """Тесты для API управления источниками HA."""

    def test_post_create_source_success(self, client):
        """T016: Успешное создание источника HA.

        Требование: POST /api/v1/devices/sources должен создавать новый источник с валидацией URL и токена.
        """
        payload = {
            "name": "My Home Assistant",
            "url": "http://192.168.1.100:8123",
            "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJoYSIsImV4cCI6MTcyNzYwMDAwMH0",
        }

        response = client.post("/api/v1/devices/sources", json=payload)

        assert response.status_code == 201, (
            f"Expected 201, got {response.status_code}: {response.text}"
        )
        data = response.json()

        # Проверяем структуру ответа
        assert "id" in data, "Response должен содержать id"
        assert data["name"] == payload["name"]
        assert data["url"] == payload["url"]
        assert data["status"] == "disconnected"  # Новый источник начинает с disconnected
        assert "created_at" in data
        assert "updated_at" in data

    def test_post_create_source_invalid_url(self, client):
        """T016: Ошибка при создании источника с невалидным URL."""
        payload = {
            "name": "Invalid HA",
            "url": "not_a_url",  # Невалидный URL
            "token": "token123",
        }

        response = client.post("/api/v1/devices/sources", json=payload)

        assert response.status_code == 422, "Должна быть ошибка валидации для неправильного URL"

    def test_post_create_source_missing_token(self, client):
        """T016: Ошибка при отсутствии токена."""
        payload = {
            "name": "No Token HA",
            "url": "http://192.168.1.100:8123",
            # Отсутствует token
        }

        response = client.post("/api/v1/devices/sources", json=payload)

        assert response.status_code == 422, "Должна быть ошибка валидации для отсутствующего token"

    def test_get_source_success(self, client):
        """T017: Успешное получение информации об источнике.

        Требование: GET /api/v1/devices/sources/{id} должен возвращать информацию об источнике.
        """
        # Сначала создаем источник
        create_payload = {
            "name": "Test HA Source",
            "url": "http://192.168.1.100:8123",
            "token": "token123abc",
        }
        create_response = client.post("/api/v1/devices/sources", json=create_payload)
        assert create_response.status_code == 201
        source_id = create_response.json()["id"]

        # Получаем источник
        response = client.get(f"/api/v1/devices/sources/{source_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == source_id
        assert data["name"] == create_payload["name"]
        assert data["url"] == create_payload["url"]

    def test_get_source_not_found(self, client):
        """T017: Ошибка при получении несуществующего источника."""
        response = client.get(f"/api/v1/devices/sources/{uuid4()}")

        assert response.status_code == 404, "Должна быть 404 для несуществующего источника"

    def test_post_sync_source_success(self, client):
        """T018: Успешный запуск синхронизации устройств из источника.

        Требование: POST /api/v1/devices/sources/{id}/sync должен запускать синхронизацию.
        """
        # Создаем источник
        create_payload = {
            "name": "Sync Test HA",
            "url": "http://192.168.1.100:8123",
            "token": "test_token",
        }
        create_response = client.post("/api/v1/devices/sources", json=create_payload)
        source_id = create_response.json()["id"]

        # Запускаем синхронизацию
        response = client.post(f"/api/v1/devices/sources/{source_id}/sync")

        # Ожидаем либо успешный запуск (202), либо 200
        assert response.status_code in [200, 202], (
            f"Expected 200 or 202, got {response.status_code}"
        )
        data = response.json()
        assert "status" in data

    def test_get_devices_list(self, client):
        """T019: Получение списка загруженных устройств.

        Требование: GET /api/v1/devices должен возвращать список всех загруженных устройств.
        """
        response = client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()

        # Ожидаем список (может быть пустой)
        assert isinstance(data, list), "GET /api/v1/devices должен возвращать список"

        # Если есть устройства, проверяем структуру
        if len(data) > 0:
            device = data[0]
            assert "id" in device
            assert "name" in device
            assert "device_type" in device
            assert "status" in device
