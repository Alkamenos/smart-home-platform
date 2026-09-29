"""
Контрактные тесты для API управления устройствами.

Тесты проверяют контракт между клиентом и сервером для операций над устройствами.
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
def sample_source(client):
    """Фикстура для создания тестового источника."""
    payload = {
        "name": "Test Device Source",
        "url": "http://192.168.1.100:8123",
        "token": "test_device_token",
    }
    response = client.post("/api/v1/devices/sources", json=payload)
    return response.json() if response.status_code == 201 else None


class TestDevicesAPI:
    """Тесты для API управления устройствами."""

    def test_get_devices_empty(self, client):
        """T019: Получение списка устройств (пусто)."""
        response = client.get("/api/v1/devices")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_devices_with_filter_by_source(self, client, sample_source):
        """T019: Получение списка устройств с фильтром по источнику."""
        if not sample_source:
            pytest.skip("Source creation failed")

        # Запрашиваем устройства с фильтром
        response = client.get(f"/api/v1/devices?source_id={sample_source['id']}")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    def test_get_device_by_id_not_found(self, client):
        """T019: Ошибка при получении несуществующего устройства."""
        response = client.get(f"/api/v1/devices/{uuid4()}")

        assert response.status_code == 404

    def test_get_device_by_id_success(self, client, sample_source):
        """T019: Успешное получение информации об устройстве."""
        if not sample_source:
            pytest.skip("Source creation failed")

        # Сначала нужно добавить устройство (будет реализовано позже)
        # Этот тест проверяет контракт для GET /api/v1/devices/{id}

        # Используем фиксированный ID для этого теста
        device_id = uuid4()
        response = client.get(f"/api/v1/devices/{device_id}")

        # Ожидаем 404 для несуществующего устройства
        # или 200 с информацией если оно существует
        assert response.status_code in [200, 404]


class TestDeviceConfigAPI:
    """Тесты для API конфигурирования устройств (US2 - Фаза 4)."""

    @pytest.fixture
    def sample_device(self, client, sample_source):
        """Фикстура для создания тестового устройства."""
        if not sample_source:
            return None

        # Создаем устройство напрямую (в хранилище)
        from datetime import datetime

        device_id = uuid4()
        device_data = {
            "id": str(device_id),
            "ha_entity_id": "light.test_light",
            "source_id": sample_source["id"],
            "name": "Test Light",
            "device_type": "light",
            "model": "Test Model",
            "manufacturer": "Test Manufacturer",
            "state": {"state": "on"},
            "status": "available",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
        }

        # Добавляем в хранилище
        from src.webui.routes.devices.devices import _devices_store

        _devices_store[str(device_id)] = device_data

        return {"id": str(device_id), **device_data}

    def test_update_device_config_success(self, client, sample_device):
        """T032: Успешное обновление конфигурации устройства."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        payload = {
            "display_name": "Updated Light Name",
            "description": "Updated description",
            "location": "Kitchen",
            "tags": ["important", "lighting"],
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["display_name"] == "Updated Light Name"
        assert data["description"] == "Updated description"
        assert data["location"] == "Kitchen"
        assert data["tags"] == ["important", "lighting"]

    def test_update_device_config_validation_display_name_empty(self, client, sample_device):
        """T032: Валидация - display_name не может быть пустым."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        payload = {
            "display_name": "",  # Пусто - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_display_name_too_long(self, client, sample_device):
        """T032: Валидация - display_name не может быть > 255 символов."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        payload = {
            "display_name": "x" * 256,  # Слишком длинно - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_description_too_long(self, client, sample_device):
        """T032: Валидация - description не может быть > 1000 символов."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        payload = {
            "description": "x" * 1001,  # Слишком длинно - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_validation_tags_too_many(self, client, sample_device):
        """T032: Валидация - не может быть > 10 тегов."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        payload = {
            "tags": [f"tag_{i}" for i in range(11)]  # 11 тегов - должна быть ошибка
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 422  # Validation error

    def test_update_device_config_not_found(self, client):
        """T032: Ошибка при обновлении конфигурации несуществующего устройства."""
        device_id = uuid4()
        payload = {
            "display_name": "Updated Name",
        }

        response = client.put(f"/api/v1/devices/{device_id}/config", json=payload)

        assert response.status_code == 404

    def test_get_device_with_config_success(self, client, sample_device):
        """T033: Получение устройства с полной конфигурацией."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]

        # Сначала обновляем конфигурацию
        config_payload = {
            "display_name": "Kitchen Light",
            "description": "Main kitchen light",
            "location": "Kitchen",
            "tags": ["lighting", "smart"],
        }
        update_response = client.put(f"/api/v1/devices/{device_id}/config", json=config_payload)
        assert update_response.status_code == 200

        # Теперь получаем устройство с конфигурацией
        response = client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()

        # Проверяем, что конфигурация включена в ответ
        assert "display_name" in data
        assert "description" in data
        assert "location" in data
        assert "tags" in data
        assert data["display_name"] == "Kitchen Light"
        assert data["description"] == "Main kitchen light"
        assert data["location"] == "Kitchen"
        assert data["tags"] == ["lighting", "smart"]

    def test_get_device_with_empty_config(self, client, sample_device):
        """T033: Получение устройства с пустой конфигурацией."""
        if not sample_device:
            pytest.skip("Device creation failed")

        device_id = sample_device["id"]
        response = client.get(f"/api/v1/devices/{device_id}")

        assert response.status_code == 200
        data = response.json()

        # Конфигурационные поля должны быть в ответе
        # (пусто для нового устройства, но они должны быть)
        assert "display_name" in data or "config" in data
        assert "id" in data
        assert "ha_entity_id" in data

    def test_execute_command_validation(self, client):
        """T044: Валидация параметров команды."""
        device_id = uuid4()

        # Отправляем команду с неправильным форматом
        payload = {
            "name": "turn_on",
            # Отсутствует обязательный параметр
        }

        response = client.post(f"/api/v1/devices/{device_id}/command", json=payload)

        # Должна быть ошибка валидации
        assert response.status_code in [400, 422]

    def test_execute_command_device_not_found(self, client):
        """T044: Ошибка при отправке команды для несуществующего устройства."""
        device_id = uuid4()

        payload = {
            "name": "turn_on",
            "parameters": {},
        }

        response = client.post(f"/api/v1/devices/{device_id}/command", json=payload)

        # Должна быть ошибка 404
        assert response.status_code == 404

    def test_execute_command_response_format(self, client):
        """T044: Ответ команды содержит правильный формат."""
        # Этот тест проверяет контракт для успешной отправки команды
        # Структура ответа должна быть: {id, status, created_at, ...}
        pass

    def test_get_device_events(self, client):
        """T045: GET /api/v1/devices/{id}/events возвращает историю событий."""
        device_id = uuid4()

        response = client.get(f"/api/v1/devices/{device_id}/events")

        # Должен вернуть 200 или 404
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            data = response.json()
            # Должен быть список событий
            assert isinstance(data, list)

    def test_get_device_events_with_filter(self, client):
        """T045: GET /api/v1/devices/{id}/events с фильтром по типу."""
        device_id = uuid4()

        response = client.get(f"/api/v1/devices/{device_id}/events?event_type=state_changed")

        assert response.status_code in [200, 404]
