"""
Интеграционные тесты для потока редактирования конфигурации устройств (US2 - Фаза 4).

Тесты проверяют полный сценарий: загрузка → редактирование конфигурации → проверка сохранения.
"""

import pytest
from fastapi.testclient import TestClient
from uuid import uuid4


@pytest.fixture
def client():
    """Фикстура для тестирования API."""
    from src.main import app
    return TestClient(app)


@pytest.fixture
def sample_device(client):
    """Фикстура для создания тестового устройства."""
    # Создаем устройство напрямую (в хранилище)
    from datetime import datetime

    device_id = uuid4()
    device_data = {
        "id": str(device_id),
        "ha_entity_id": "light.test_light",
        "source_id": str(uuid4()),
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

    return device_data


@pytest.mark.asyncio
class TestDeviceConfigIntegration:
    """Интеграционные тесты для редактирования конфигурации устройств."""

    @pytest.mark.skip(reason="Зависит от T032-T033 реализации")
    async def test_full_config_edit_flow(self, client, sample_device):
        """T034: Полный поток редактирования конфигурации устройства.

        Сценарий:
        1. Загрузить устройство через API
        2. Редактировать конфигурацию (display_name, description, location, tags)
        3. Проверить, что изменения сохранены
        4. Загрузить устройство снова
        5. Проверить, что конфигурация восстановилась
        """
        device_id = sample_device["id"]

        # 1. Загружаем устройство
        get_response = client.get(f"/api/v1/devices/{device_id}")
        assert get_response.status_code == 200
        original_device = get_response.json()

        # 2. Редактируем конфигурацию
        config_payload = {
            "display_name": "Кухонный свет",
            "description": "Основное освещение кухни",
            "location": "Кухня",
            "tags": ["lighting", "kitchen", "smart"]
        }
        update_response = client.put(
            f"/api/v1/devices/{device_id}/config",
            json=config_payload
        )

        assert update_response.status_code == 200
        updated_device = update_response.json()

        # 3. Проверяем, что изменения применены
        assert updated_device["display_name"] == "Кухонный свет"
        assert updated_device["description"] == "Основное освещение кухни"
        assert updated_device["location"] == "Кухня"
        assert updated_device["tags"] == ["lighting", "kitchen", "smart"]

        # 4. Загружаем устройство снова (имитируем перезагрузку)
        reload_response = client.get(f"/api/v1/devices/{device_id}")
        assert reload_response.status_code == 200
        reloaded_device = reload_response.json()

        # 5. Проверяем, что конфигурация восстановилась (T042)
        assert reloaded_device["display_name"] == "Кухонный свет"
        assert reloaded_device["description"] == "Основное освещение кухни"
        assert reloaded_device["location"] == "Кухня"
        assert reloaded_device["tags"] == ["lighting", "kitchen", "smart"]

    @pytest.mark.skip(reason="Зависит от T032-T033 реализации")
    async def test_config_validation_error_handling(self, client, sample_device):
        """T034: Обработка ошибок валидации при редактировании конфигурации."""
        device_id = sample_device["id"]

        # Пытаемся установить display_name слишком длинным
        invalid_payload = {
            "display_name": "x" * 256,  # > 255 символов
        }
        response = client.put(
            f"/api/v1/devices/{device_id}/config",
            json=invalid_payload
        )

        # Ожидаем ошибку валидации
        assert response.status_code == 422

    @pytest.mark.skip(reason="Зависит от T032-T033 реализации")
    async def test_config_partial_update(self, client, sample_device):
        """T034: Частичное обновление конфигурации (обновляем только некоторые поля)."""
        device_id = sample_device["id"]

        # Сначала устанавливаем полную конфигурацию
        full_config = {
            "display_name": "Test Light",
            "description": "Test Description",
            "location": "Test Location",
            "tags": ["test"]
        }
        update_response = client.put(
            f"/api/v1/devices/{device_id}/config",
            json=full_config
        )
        assert update_response.status_code == 200

        # Теперь обновляем только display_name
        partial_update = {
            "display_name": "Updated Light Name"
        }
        partial_response = client.put(
            f"/api/v1/devices/{device_id}/config",
            json=partial_update
        )
        assert partial_response.status_code == 200
        updated_device = partial_response.json()

        # Проверяем, что display_name изменился, а остальное осталось
        assert updated_device["display_name"] == "Updated Light Name"
        assert updated_device["description"] == "Test Description"
        assert updated_device["location"] == "Test Location"
        assert updated_device["tags"] == ["test"]
