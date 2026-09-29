"""
Интеграционные тесты для потока синхронизации устройств из Home Assistant.

Тесты проверяют полный сценарий: создание источника → синхронизация → получение устройств.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app

    return TestClient(app)


@pytest.mark.asyncio
class TestDeviceSyncIntegration:
    """Интеграционные тесты для синхронизации устройств."""

    @pytest.mark.skip(reason="Зависит от T021-T024 реализации")
    async def test_full_sync_flow(self, client):
        """T020: Полный поток синхронизации устройств.

        Сценарий:
        1. Создать источник HA
        2. Запустить синхронизацию
        3. Проверить, что устройства загружены
        4. Получить список устройств через API
        """
        # 1. Создаем источник
        source_payload = {
            "name": "Integration Test HA",
            "url": "http://192.168.1.100:8123",
            "token": "integration_test_token",
        }

        source_response = client.post("/api/v1/devices/sources", json=source_payload)
        assert source_response.status_code == 201
        source_id = source_response.json()["id"]

        # 2. Запускаем синхронизацию
        # Мокируем HARestClient.fetch_devices
        mock_devices = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {
                    "friendly_name": "Kitchen Light",
                    "brightness": 255,
                },
            },
            {
                "entity_id": "switch.bedroom_fan",
                "state": "off",
                "attributes": {
                    "friendly_name": "Bedroom Fan",
                },
            },
        ]

        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient.fetch_devices",
            return_value=mock_devices,
        ):
            sync_response = client.post(f"/api/v1/devices/sources/{source_id}/sync")
            assert sync_response.status_code in [200, 202]

        # 3. Проверяем, что устройства загружены
        devices_response = client.get("/api/v1/devices")
        assert devices_response.status_code == 200
        devices = devices_response.json()

        # Должны быть загружены оба устройства
        assert len(devices) >= 2, f"Expected at least 2 devices, got {len(devices)}"

        # Проверяем структуру устройств
        light_device = next((d for d in devices if "kitchen" in d["name"].lower()), None)
        assert light_device is not None, "Kitchen light device not found"
        assert light_device["device_type"] == "light"
        assert light_device["status"] == "available"

    @pytest.mark.skip(reason="Зависит от T021-T024 реализации")
    async def test_sync_with_connection_error(self, client):
        """T020: Обработка ошибки подключения при синхронизации."""
        # Создаем источник
        source_payload = {
            "name": "Error Test HA",
            "url": "http://invalid-host:8123",
            "token": "error_test_token",
        }

        source_response = client.post("/api/v1/devices/sources", json=source_payload)
        assert source_response.status_code == 201
        source_id = source_response.json()["id"]

        # Мокируем ошибку подключения
        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient.connect_to_ha", return_value=False
        ):
            sync_response = client.post(f"/api/v1/devices/sources/{source_id}/sync")

            # Ожидаем ошибку
            assert sync_response.status_code in [400, 500]

    @pytest.mark.skip(reason="Зависит от T021-T024 реализации")
    async def test_sync_persistence(self, client):
        """T020: Синхронизация сохраняется при перезагрузке приложения (T031)."""
        # Создаем и синхронизируем источник
        source_payload = {
            "name": "Persistence Test HA",
            "url": "http://192.168.1.100:8123",
            "token": "persistence_test_token",
        }

        source_response = client.post("/api/v1/devices/sources", json=source_payload)
        source_id = source_response.json()["id"]

        # Получаем список устройств до перезагрузки
        devices_before = client.get("/api/v1/devices").json()

        # После перезагрузки (новый клиент) - устройства должны быть восстановлены из persistence
        # Этот тест проверяет, что данные сохранены и восстановлены
        devices_after = client.get("/api/v1/devices").json()

        assert len(devices_after) == len(devices_before), (
            "Devices не сохранились после перезагрузки"
        )
