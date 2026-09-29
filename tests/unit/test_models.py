"""
Полный набор unit тестов для валидации всех моделей Smart Home Platform.

Тестирует следующие модели:
- HASource: источник Home Assistant
- Device: устройство в платформе
- DeviceConfig: конфигурация устройства
- DeviceCommand: команда устройства
- DeviceAccess: контроль доступа к устройству

Требования к тестовому покрытию:
- Валидные данные (успешное создание)
- Невалидные данные (ошибки валидации)
- Граничные значения (min/max длины, уникальность)
- Преобразование типов (JSON <-> модель)
- Минимум 90% покрытие
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import json
from datetime import datetime
from typing import Any, Dict
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from src.core.models.device import Device
from src.core.models.device_access import DeviceAccess
from src.core.models.device_command import (
    CommandExecutionRequest,
    CommandExecutionResponse,
    DeviceCommand,
)
from src.core.models.device_config import DeviceConfig
from src.core.models.ha_source import HASource


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def valid_ha_source_data() -> Dict[str, Any]:
    """Валидные данные для HASource."""
    return {
        "name": "Home Assistant Pro",
        "url": "http://192.168.1.100:8123",
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" * 2,  # минимум 10 символов
        "status": "connected",
    }


@pytest.fixture
def valid_device_data() -> Dict[str, Any]:
    """Валидные данные для Device."""
    return {
        "ha_entity_id": "light.kitchen_light",
        "source_id": uuid4(),
        "name": "Kitchen Light",
        "device_type": "light",
    }


@pytest.fixture
def valid_device_config_data() -> Dict[str, Any]:
    """Валидные данные для DeviceConfig."""
    return {
        "device_id": uuid4(),
        "display_name": "Кухонный свет",
        "description": "Основное освещение кухни",
        "location": "Кухня",
        "tags": ["lighting", "kitchen"],
    }


@pytest.fixture
def valid_device_command_data() -> Dict[str, Any]:
    """Валидные данные для DeviceCommand."""
    return {
        "device_id": uuid4(),
        "name": "turn_on",
        "ha_service": "light.turn_on",
        "description": "Включить свет",
        "parameters": {
            "brightness": {"type": "integer", "min": 0, "max": 255},
        },
        "execution_timeout": 30,
    }


@pytest.fixture
def valid_device_access_data() -> Dict[str, Any]:
    """Валидные данные для DeviceAccess."""
    return {
        "device_id": uuid4(),
        "user_id": "user_123",
        "role": "controller",
        "granted_by": "admin_user",
    }


# ============================================================================
# ТЕСТЫ HASource
# ============================================================================

class TestHASourceCreation:
    """Тесты создания и валидации HASource."""

    def test_создание_с_валидными_данными(self, valid_ha_source_data):
        """Успешное создание HASource с валидными данными."""
        source = HASource(**valid_ha_source_data)

        assert source.name == "Home Assistant Pro"
        assert str(source.url) == "http://192.168.1.100:8123/"
        assert source.status == "connected"
        assert source.token == valid_ha_source_data["token"]
        assert source.device_count == 0
        assert isinstance(source.id, UUID)
        assert isinstance(source.created_at, datetime)

    def test_создание_с_минимальными_данными(self):
        """Создание HASource только с обязательными полями."""
        source = HASource(
            name="HA Instance",
            url="http://localhost:8123",
            token="long_token_string_at_least_10_chars"
        )

        assert source.name == "HA Instance"
        assert source.status == "disconnected"  # по умолчанию
        assert source.last_sync is None
        assert source.last_error is None

    def test_создание_с_uuid(self):
        """Создание HASource с явным указанием UUID."""
        test_id = uuid4()
        source = HASource(
            id=test_id,
            name="Test",
            url="http://localhost:8123",
            token="test_token_123456"
        )

        assert source.id == test_id

    def test_json_schema_валидация(self, valid_ha_source_data):
        """Проверка JSON schema валидации."""
        source = HASource(**valid_ha_source_data)
        json_str = source.model_dump_json()

        # Проверяем что данные корректно сериализуются
        assert json_str is not None
        assert "name" in json_str
        assert "Home Assistant Pro" in json_str


class TestHASourceNameValidation:
    """Тесты валидации поля 'name' в HASource."""

    def test_имя_минимальной_длины(self):
        """Имя может быть 1 символом."""
        source = HASource(
            name="A",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.name == "A"

    def test_имя_максимальной_длины(self):
        """Имя может быть 255 символами."""
        long_name = "A" * 255
        source = HASource(
            name=long_name,
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.name == long_name
        assert len(source.name) == 255

    def test_имя_превышает_максимум(self):
        """Имя более 255 символов вызывает ошибку."""
        too_long_name = "A" * 256

        with pytest.raises(ValidationError) as exc_info:
            HASource(
                name=too_long_name,
                url="http://localhost:8123",
                token="token_min_10_chars_here"
            )

        assert "String should have at most 255 characters" in str(exc_info.value)

    def test_пустое_имя(self):
        """Пустое имя вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            HASource(
                name="",
                url="http://localhost:8123",
                token="token_min_10_chars_here"
            )

        assert "String should have at least 1 character" in str(exc_info.value)

    def test_имя_с_специальными_символами(self):
        """Имя может содержать специальные символы."""
        special_name = "Home Assistant Pro (测试) - Тест!"
        source = HASource(
            name=special_name,
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.name == special_name


class TestHASourceURLValidation:
    """Тесты валидации поля 'url' в HASource."""

    def test_валидный_url_с_портом(self):
        """Валидный HTTP URL с портом."""
        source = HASource(
            name="Test",
            url="http://192.168.1.100:8123",
            token="token_min_10_chars_here"
        )
        assert "192.168.1.100" in str(source.url)

    def test_валидный_https_url(self):
        """Валидный HTTPS URL."""
        source = HASource(
            name="Test",
            url="https://home.example.com",
            token="token_min_10_chars_here"
        )
        assert "https" in str(source.url)

    def test_невалидный_url_без_протокола(self):
        """URL без протокола вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            HASource(
                name="Test",
                url="localhost:8123",
                token="token_min_10_chars_here"
            )
        assert "Invalid URL" in str(exc_info.value) or "url" in str(exc_info.value).lower()

    def test_невалидный_url_пустой(self):
        """Пустой URL вызывает ошибку."""
        with pytest.raises(ValidationError):
            HASource(
                name="Test",
                url="",
                token="token_min_10_chars_here"
            )

    def test_url_с_путём(self):
        """URL может содержать путь."""
        source = HASource(
            name="Test",
            url="http://localhost:8123/ha",
            token="token_min_10_chars_here"
        )
        assert "/ha" in str(source.url)


class TestHASourceTokenValidation:
    """Тесты валидации поля 'token' в HASource."""

    def test_валидный_токен_минимальная_длина(self):
        """Токен минимальной длины (10 символов)."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="0123456789"
        )
        assert source.token == "0123456789"

    def test_валидный_токен_длинный(self):
        """Долгоживущий токен из примера."""
        long_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token=long_token
        )
        assert source.token == long_token

    def test_токен_менее_10_символов(self):
        """Токен менее 10 символов вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            HASource(
                name="Test",
                url="http://localhost:8123",
                token="short"
            )

        assert "String should have at least 10 characters" in str(exc_info.value)

    def test_пустой_токен(self):
        """Пустой токен вызывает ошибку."""
        with pytest.raises(ValidationError):
            HASource(
                name="Test",
                url="http://localhost:8123",
                token=""
            )

    def test_токен_с_специальными_символами(self):
        """Токен может содержать специальные символы."""
        special_token = "token_with_!@#$%^&*()_+-=[]{}|;:,.<>?"
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token=special_token
        )
        assert source.token == special_token


class TestHASourceStatusValidation:
    """Тесты валидации поля 'status' в HASource."""

    def test_статус_connected(self):
        """Статус 'connected'."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here",
            status="connected"
        )
        assert source.status == "connected"

    def test_статус_disconnected(self):
        """Статус 'disconnected' по умолчанию."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.status == "disconnected"

    def test_статус_error(self):
        """Статус 'error'."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here",
            status="error"
        )
        assert source.status == "error"

    def test_пользовательский_статус(self):
        """Пользовательский статус также допускается."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here",
            status="custom_status"
        )
        assert source.status == "custom_status"


class TestHASourceOptionalFields:
    """Тесты опциональных полей HASource."""

    def test_last_sync_по_умолчанию_none(self):
        """last_sync по умолчанию None."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.last_sync is None

    def test_last_sync_с_значением(self):
        """last_sync с явным значением datetime."""
        now = datetime.utcnow()
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here",
            last_sync=now
        )
        assert source.last_sync == now

    def test_device_count_по_умолчанию_ноль(self):
        """device_count по умолчанию 0."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        assert source.device_count == 0

    def test_device_count_с_значением(self):
        """device_count с явным значением."""
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here",
            device_count=47
        )
        assert source.device_count == 47


# ============================================================================
# ТЕСТЫ Device
# ============================================================================

class TestDeviceCreation:
    """Тесты создания и валидации Device."""

    def test_создание_с_валидными_данными(self, valid_device_data):
        """Успешное создание Device с валидными данными."""
        device = Device(**valid_device_data)

        assert device.ha_entity_id == "light.kitchen_light"
        assert device.name == "Kitchen Light"
        assert device.device_type == "light"
        assert device.status == "available"
        assert isinstance(device.id, UUID)

    def test_создание_с_минимальными_данными(self):
        """Создание Device только с обязательными полями."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Kitchen",
            device_type="light"
        )

        assert device.ha_entity_id == "light.kitchen"
        assert device.device_type == "light"
        assert device.state == {}
        assert device.attributes == {}

    def test_json_сериализация(self, valid_device_data):
        """Device корректно сериализуется в JSON."""
        device = Device(**valid_device_data)
        json_str = device.model_dump_json()

        assert json_str is not None
        assert "light.kitchen_light" in json_str
        assert "Kitchen Light" in json_str


class TestDeviceEntityIDValidation:
    """Тесты валидации поля 'ha_entity_id' в Device."""

    def test_валидный_entity_id_простой(self):
        """Валидный entity_id простого формата."""
        device = Device(
            ha_entity_id="light.kitchen_light",
            source_id=uuid4(),
            name="Test",
            device_type="light"
        )
        assert device.ha_entity_id == "light.kitchen_light"

    def test_валидный_entity_id_с_числами(self):
        """Entity_id может содержать цифры."""
        device = Device(
            ha_entity_id="light.kitchen_1_light_2",
            source_id=uuid4(),
            name="Test",
            device_type="light"
        )
        assert device.ha_entity_id == "light.kitchen_1_light_2"

    def test_невалидный_entity_id_нет_точки(self):
        """Entity_id без точки вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            Device(
                ha_entity_id="light_kitchen",
                source_id=uuid4(),
                name="Test",
                device_type="light"
            )
        assert "pattern" in str(exc_info.value).lower()

    def test_невалидный_entity_id_заглавные_буквы(self):
        """Entity_id с заглавными буквами вызывает ошибку."""
        with pytest.raises(ValidationError):
            Device(
                ha_entity_id="Light.Kitchen",
                source_id=uuid4(),
                name="Test",
                device_type="light"
            )

    def test_невалидный_entity_id_спецсимволы(self):
        """Entity_id со спецсимволами вызывает ошибку."""
        with pytest.raises(ValidationError):
            Device(
                ha_entity_id="light.kitchen@light",
                source_id=uuid4(),
                name="Test",
                device_type="light"
            )

    def test_невалидный_entity_id_пустой(self):
        """Пустой entity_id вызывает ошибку."""
        with pytest.raises(ValidationError):
            Device(
                ha_entity_id="",
                source_id=uuid4(),
                name="Test",
                device_type="light"
            )


class TestDeviceDeviceTypeValidation:
    """Тесты валидации поля 'device_type' в Device."""

    def test_device_type_light(self):
        """Device type 'light'."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light"
        )
        assert device.device_type == "light"

    def test_device_type_switch(self):
        """Device type 'switch'."""
        device = Device(
            ha_entity_id="switch.heater",
            source_id=uuid4(),
            name="Test",
            device_type="switch"
        )
        assert device.device_type == "switch"

    def test_device_type_климат(self):
        """Device type 'climate'."""
        device = Device(
            ha_entity_id="climate.bedroom",
            source_id=uuid4(),
            name="Test",
            device_type="climate"
        )
        assert device.device_type == "climate"

    def test_device_type_с_датчиком(self):
        """Device type может быть любой строкой."""
        device = Device(
            ha_entity_id="sensor.temperature",
            source_id=uuid4(),
            name="Test",
            device_type="sensor"
        )
        assert device.device_type == "sensor"

    def test_device_type_пустой(self):
        """Пустой device_type допускается."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type=""
        )
        assert device.device_type == ""


class TestDeviceStateValidation:
    """Тесты валидации поля 'state' в Device."""

    def test_state_пусто_по_умолчанию(self, valid_device_data):
        """state по умолчанию пустой dict."""
        device = Device(**valid_device_data)
        assert device.state == {}

    def test_state_с_значениями(self):
        """state может содержать значения состояния."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            state={"state": "on", "brightness": 200}
        )
        assert device.state["state"] == "on"
        assert device.state["brightness"] == 200

    def test_state_сложный_объект(self):
        """state может быть сложным объектом."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            state={
                "state": "on",
                "brightness": 200,
                "color": {"h": 180, "s": 100}
            }
        )
        assert device.state["color"]["h"] == 180


class TestDeviceStatusValidation:
    """Тесты валидации поля 'status' в Device."""

    def test_статус_available_по_умолчанию(self, valid_device_data):
        """status по умолчанию 'available'."""
        device = Device(**valid_device_data)
        assert device.status == "available"

    def test_статус_unavailable(self):
        """status 'unavailable'."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            status="unavailable"
        )
        assert device.status == "unavailable"

    def test_статус_removed_from_ha(self):
        """status 'removed_from_ha'."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            status="removed_from_ha"
        )
        assert device.status == "removed_from_ha"

    def test_пользовательский_статус(self):
        """Пользовательский статус допускается."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            status="custom_status"
        )
        assert device.status == "custom_status"


class TestDeviceNameValidation:
    """Тесты валидации поля 'name' в Device."""

    def test_имя_минимальной_длины(self):
        """Имя минимальной длины (1 символ)."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="A",
            device_type="light"
        )
        assert device.name == "A"

    def test_имя_максимальной_длины(self):
        """Имя максимальной длины (255 символов)."""
        long_name = "A" * 255
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name=long_name,
            device_type="light"
        )
        assert device.name == long_name

    def test_имя_превышает_максимум(self):
        """Имя более 255 символов вызывает ошибку."""
        too_long_name = "A" * 256

        with pytest.raises(ValidationError):
            Device(
                ha_entity_id="light.kitchen",
                source_id=uuid4(),
                name=too_long_name,
                device_type="light"
            )

    def test_пустое_имя(self):
        """Пустое имя вызывает ошибку."""
        with pytest.raises(ValidationError):
            Device(
                ha_entity_id="light.kitchen",
                source_id=uuid4(),
                name="",
                device_type="light"
            )


# ============================================================================
# ТЕСТЫ DeviceConfig
# ============================================================================

class TestDeviceConfigCreation:
    """Тесты создания и валидации DeviceConfig."""

    def test_создание_с_валидными_данными(self, valid_device_config_data):
        """Успешное создание DeviceConfig с валидными данными."""
        config = DeviceConfig(**valid_device_config_data)

        assert config.display_name == "Кухонный свет"
        assert config.location == "Кухня"
        assert config.tags == ["lighting", "kitchen"]
        assert config.enabled is True
        assert isinstance(config.id, UUID)

    def test_создание_с_минимальными_данными(self):
        """Создание DeviceConfig только с обязательными полями."""
        config = DeviceConfig(device_id=uuid4())

        assert config.device_id is not None
        assert config.display_name is None
        assert config.location is None
        assert config.tags is None
        assert config.enabled is True

    def test_json_сериализация(self, valid_device_config_data):
        """DeviceConfig корректно сериализуется в JSON."""
        config = DeviceConfig(**valid_device_config_data)
        json_str = config.model_dump_json()

        assert json_str is not None
        assert "Кухонный свет" in json_str


class TestDeviceConfigDisplayNameValidation:
    """Тесты валидации поля 'display_name' в DeviceConfig."""

    def test_valid_display_name(self):
        """Валидное display_name."""
        config = DeviceConfig(
            device_id=uuid4(),
            display_name="Кухонный свет"
        )
        assert config.display_name == "Кухонный свет"

    def test_display_name_минимальной_длины(self):
        """display_name минимальной длины (1 символ)."""
        config = DeviceConfig(
            device_id=uuid4(),
            display_name="А"
        )
        assert config.display_name == "А"

    def test_display_name_максимальной_длины(self):
        """display_name максимальной длины (255 символов)."""
        long_name = "А" * 255
        config = DeviceConfig(
            device_id=uuid4(),
            display_name=long_name
        )
        assert config.display_name == long_name

    def test_display_name_превышает_максимум(self):
        """display_name более 255 символов вызывает ошибку."""
        too_long_name = "А" * 256

        with pytest.raises(ValidationError):
            DeviceConfig(
                device_id=uuid4(),
                display_name=too_long_name
            )

    def test_display_name_только_пробелы(self):
        """display_name только из пробелов вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                display_name="   "
            )
        assert "display_name не может быть пустым" in str(exc_info.value)

    def test_display_name_пустой_вызывает_ошибку(self):
        """Пустой display_name вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                display_name=""
            )
        assert "display_name не может быть пустым" in str(exc_info.value)

    def test_display_name_none(self):
        """display_name может быть None."""
        config = DeviceConfig(
            device_id=uuid4(),
            display_name=None
        )
        assert config.display_name is None


class TestDeviceConfigTagsValidation:
    """Тесты валидации поля 'tags' в DeviceConfig."""

    def test_tags_валидные(self):
        """Валидные теги."""
        config = DeviceConfig(
            device_id=uuid4(),
            tags=["lighting", "kitchen"]
        )
        assert config.tags == ["lighting", "kitchen"]

    def test_tags_один_тег(self):
        """Один тег."""
        config = DeviceConfig(
            device_id=uuid4(),
            tags=["lighting"]
        )
        assert config.tags == ["lighting"]

    def test_tags_максимум_10(self):
        """Максимум 10 тегов."""
        tags = [f"tag_{i}" for i in range(10)]
        config = DeviceConfig(
            device_id=uuid4(),
            tags=tags
        )
        assert len(config.tags) == 10

    def test_tags_более_10(self):
        """Более 10 тегов вызывает ошибку."""
        tags = [f"tag_{i}" for i in range(11)]

        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                tags=tags
            )
        assert "Не может быть более 10 тегов" in str(exc_info.value)

    def test_tags_длинный_тег(self):
        """Тег максимальной длины (50 символов)."""
        long_tag = "a" * 50
        config = DeviceConfig(
            device_id=uuid4(),
            tags=[long_tag]
        )
        assert config.tags[0] == long_tag

    def test_tags_тег_более_50_символов(self):
        """Тег более 50 символов вызывает ошибку."""
        too_long_tag = "a" * 51

        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                tags=[too_long_tag]
            )
        assert "слишком длинный" in str(exc_info.value)

    def test_tags_пустой_тег(self):
        """Пустой тег вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                tags=["valid_tag", ""]
            )
        assert "не могут быть пустыми" in str(exc_info.value)

    def test_tags_тег_только_пробелы(self):
        """Тег только из пробелов вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceConfig(
                device_id=uuid4(),
                tags=["valid_tag", "   "]
            )
        assert "не могут быть пустыми" in str(exc_info.value)

    def test_tags_пусто_по_умолчанию(self):
        """tags по умолчанию None."""
        config = DeviceConfig(device_id=uuid4())
        assert config.tags is None

    def test_tags_пустой_список(self):
        """Пустой список тегов допускается."""
        config = DeviceConfig(
            device_id=uuid4(),
            tags=[]
        )
        assert config.tags == []


class TestDeviceConfigLocationValidation:
    """Тесты валидации поля 'location' в DeviceConfig."""

    def test_валидное_location(self):
        """Валидное location."""
        config = DeviceConfig(
            device_id=uuid4(),
            location="Кухня"
        )
        assert config.location == "Кухня"

    def test_location_максимальной_длины(self):
        """location максимальной длины (255 символов)."""
        long_location = "А" * 255
        config = DeviceConfig(
            device_id=uuid4(),
            location=long_location
        )
        assert config.location == long_location

    def test_location_превышает_максимум(self):
        """location более 255 символов вызывает ошибку."""
        too_long_location = "А" * 256

        with pytest.raises(ValidationError):
            DeviceConfig(
                device_id=uuid4(),
                location=too_long_location
            )

    def test_location_none_по_умолчанию(self):
        """location по умолчанию None."""
        config = DeviceConfig(device_id=uuid4())
        assert config.location is None


class TestDeviceConfigDescriptionValidation:
    """Тесты валидации поля 'description' в DeviceConfig."""

    def test_валидное_description(self):
        """Валидное description."""
        config = DeviceConfig(
            device_id=uuid4(),
            description="Основное освещение кухни"
        )
        assert config.description == "Основное освещение кухни"

    def test_description_максимальной_длины(self):
        """description максимальной длины (1000 символов)."""
        long_description = "А" * 1000
        config = DeviceConfig(
            device_id=uuid4(),
            description=long_description
        )
        assert config.description == long_description

    def test_description_превышает_максимум(self):
        """description более 1000 символов вызывает ошибку."""
        too_long_description = "А" * 1001

        with pytest.raises(ValidationError):
            DeviceConfig(
                device_id=uuid4(),
                description=too_long_description
            )

    def test_description_пусто_по_умолчанию(self):
        """description по умолчанию None."""
        config = DeviceConfig(device_id=uuid4())
        assert config.description is None


# ============================================================================
# ТЕСТЫ DeviceCommand
# ============================================================================

class TestDeviceCommandCreation:
    """Тесты создания и валидации DeviceCommand."""

    def test_создание_с_валидными_данными(self, valid_device_command_data):
        """Успешное создание DeviceCommand с валидными данными."""
        command = DeviceCommand(**valid_device_command_data)

        assert command.name == "turn_on"
        assert command.ha_service == "light.turn_on"
        assert command.execution_timeout == 30
        assert command.is_safe is True
        assert command.enabled is True
        assert isinstance(command.id, UUID)

    def test_создание_с_минимальными_данными(self):
        """Создание DeviceCommand только с обязательными полями."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test_command",
            ha_service="domain.service"
        )

        assert command.device_id is not None
        assert command.name == "test_command"
        assert command.ha_service == "domain.service"
        assert command.execution_timeout == 30  # значение по умолчанию
        assert command.parameters == {}

    def test_json_сериализация(self, valid_device_command_data):
        """DeviceCommand корректно сериализуется в JSON."""
        command = DeviceCommand(**valid_device_command_data)
        json_str = command.model_dump_json()

        assert json_str is not None
        assert "turn_on" in json_str
        assert "light.turn_on" in json_str


class TestDeviceCommandNameValidation:
    """Тесты валидации поля 'name' в DeviceCommand."""

    def test_валидное_name(self):
        """Валидное name."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="turn_on",
            ha_service="light.turn_on"
        )
        assert command.name == "turn_on"

    def test_name_минимальной_длины(self):
        """name минимальной длины (1 символ)."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="a",
            ha_service="light.turn_on"
        )
        assert command.name == "a"

    def test_name_максимальной_длины(self):
        """name максимальной длины (255 символов)."""
        long_name = "a" * 255
        command = DeviceCommand(
            device_id=uuid4(),
            name=long_name,
            ha_service="light.turn_on"
        )
        assert command.name == long_name

    def test_name_превышает_максимум(self):
        """name более 255 символов вызывает ошибку."""
        too_long_name = "a" * 256

        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name=too_long_name,
                ha_service="light.turn_on"
            )

    def test_пустое_name(self):
        """Пустое name вызывает ошибку."""
        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name="",
                ha_service="light.turn_on"
            )


class TestDeviceCommandHAServiceValidation:
    """Тесты валидации поля 'ha_service' в DeviceCommand."""

    def test_валидный_ha_service(self):
        """Валидный ha_service."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on"
        )
        assert command.ha_service == "light.turn_on"

    def test_ha_service_switch_toggle(self):
        """ha_service для switch."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="switch.toggle"
        )
        assert command.ha_service == "switch.toggle"

    def test_ha_service_climate_set_temperature(self):
        """ha_service для climate."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="climate.set_temperature"
        )
        assert command.ha_service == "climate.set_temperature"

    def test_ha_service_с_подчёркиванием(self):
        """ha_service с подчёркиванием."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light_group.turn_on"
        )
        assert command.ha_service == "light_group.turn_on"

    def test_невалидный_ha_service_нет_точки(self):
        """ha_service без точки вызывает ошибку."""
        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name="test",
                ha_service="light_turn_on"
            )

    def test_невалидный_ha_service_заглавные_буквы(self):
        """ha_service с заглавными буквами вызывает ошибку."""
        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name="test",
                ha_service="Light.TurnOn"
            )

    def test_невалидный_ha_service_спецсимволы(self):
        """ha_service со спецсимволами вызывает ошибку."""
        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name="test",
                ha_service="light.turn@on"
            )


class TestDeviceCommandTimeoutValidation:
    """Тесты валидации поля 'execution_timeout' в DeviceCommand."""

    def test_timeout_по_умолчанию_30(self):
        """Timeout по умолчанию 30 секунд."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on"
        )
        assert command.execution_timeout == 30

    def test_timeout_минимум_1(self):
        """Timeout минимум 1 секунда."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            execution_timeout=1
        )
        assert command.execution_timeout == 1

    def test_timeout_максимум_300(self):
        """Timeout максимум 300 секунд."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            execution_timeout=300
        )
        assert command.execution_timeout == 300

    def test_timeout_ноль_вызывает_ошибку(self):
        """Timeout 0 вызывает ошибку."""
        with pytest.raises(ValidationError):
            DeviceCommand(
                device_id=uuid4(),
                name="test",
                ha_service="light.turn_on",
                execution_timeout=0
            )

    def test_timeout_более_300_вызывает_ошибку(self):
        """Timeout более 300 вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceCommand(
                device_id=uuid4(),
                name="test",
                ha_service="light.turn_on",
                execution_timeout=301
            )
        assert "execution_timeout must be <= 300 seconds" in str(exc_info.value)


class TestDeviceCommandParametersValidation:
    """Тесты валидации поля 'parameters' в DeviceCommand."""

    def test_parameters_пусто_по_умолчанию(self):
        """parameters по умолчанию пустой dict."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on"
        )
        assert command.parameters == {}

    def test_parameters_с_одним_параметром(self):
        """parameters с одним параметром."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            parameters={"brightness": {"type": "integer", "min": 0, "max": 255}}
        )
        assert "brightness" in command.parameters

    def test_parameters_с_несколькими_параметрами(self):
        """parameters с несколькими параметрами."""
        params = {
            "brightness": {"type": "integer"},
            "color_temp": {"type": "integer"},
            "transition": {"type": "float"}
        }
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            parameters=params
        )
        assert len(command.parameters) == 3

    def test_parameters_сложная_структура(self):
        """parameters может быть сложной структурой."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            parameters={
                "color": {
                    "type": "object",
                    "properties": {
                        "h": {"type": "number"},
                        "s": {"type": "number"}
                    }
                }
            }
        )
        assert command.parameters["color"]["type"] == "object"


class TestDeviceCommandSafetyValidation:
    """Тесты валидации поля 'is_safe' в DeviceCommand."""

    def test_is_safe_по_умолчанию_true(self):
        """is_safe по умолчанию True."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on"
        )
        assert command.is_safe is True

    def test_is_safe_false(self):
        """is_safe может быть False."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            is_safe=False
        )
        assert command.is_safe is False


# ============================================================================
# ТЕСТЫ DeviceAccess
# ============================================================================

class TestDeviceAccessCreation:
    """Тесты создания и валидации DeviceAccess."""

    def test_создание_с_валидными_данными(self, valid_device_access_data):
        """Успешное создание DeviceAccess с валидными данными."""
        access = DeviceAccess(**valid_device_access_data)

        assert access.device_id == valid_device_access_data["device_id"]
        assert access.user_id == "user_123"
        assert access.role == "controller"
        assert access.granted_by == "admin_user"
        assert isinstance(access.id, UUID)

    def test_создание_с_минимальными_данными(self):
        """Создание DeviceAccess только с обязательными полями."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="viewer",
            granted_by="admin"
        )

        assert access.device_id is not None
        assert access.user_id == "user_123"
        assert access.role == "viewer"

    def test_json_сериализация(self, valid_device_access_data):
        """DeviceAccess корректно сериализуется в JSON."""
        access = DeviceAccess(**valid_device_access_data)
        json_str = access.model_dump_json()

        assert json_str is not None
        assert "user_123" in json_str
        assert "controller" in json_str


class TestDeviceAccessRoleValidation:
    """Тесты валидации поля 'role' в DeviceAccess."""

    def test_роль_viewer(self):
        """Роль 'viewer'."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="viewer",
            granted_by="admin"
        )
        assert access.role == "viewer"

    def test_роль_controller(self):
        """Роль 'controller'."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="controller",
            granted_by="admin"
        )
        assert access.role == "controller"

    def test_роль_admin(self):
        """Роль 'admin'."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="admin",
            granted_by="admin"
        )
        assert access.role == "admin"

    def test_невалидная_роль(self):
        """Невалидная роль вызывает ошибку."""
        with pytest.raises(ValidationError) as exc_info:
            DeviceAccess(
                device_id=uuid4(),
                user_id="user_123",
                role="invalid_role",  # type: ignore
                granted_by="admin"
            )
        assert "role" in str(exc_info.value).lower()


class TestDeviceAccessPermissions:
    """Тесты методов проверки прав доступа."""

    def test_viewer_может_просматривать(self):
        """Роль viewer может просматривать."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="viewer",
            granted_by="admin"
        )
        assert access.can_view() is True

    def test_viewer_не_может_управлять(self):
        """Роль viewer не может управлять."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="viewer",
            granted_by="admin"
        )
        assert access.can_control() is False

    def test_viewer_не_может_управлять_доступом(self):
        """Роль viewer не может управлять доступом."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="viewer",
            granted_by="admin"
        )
        assert access.can_manage_access() is False

    def test_controller_может_просматривать(self):
        """Роль controller может просматривать."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="controller",
            granted_by="admin"
        )
        assert access.can_view() is True

    def test_controller_может_управлять(self):
        """Роль controller может управлять."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="controller",
            granted_by="admin"
        )
        assert access.can_control() is True

    def test_controller_не_может_управлять_доступом(self):
        """Роль controller не может управлять доступом."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="controller",
            granted_by="admin"
        )
        assert access.can_manage_access() is False

    def test_admin_может_всё(self):
        """Роль admin может всё."""
        access = DeviceAccess(
            device_id=uuid4(),
            user_id="user_123",
            role="admin",
            granted_by="admin"
        )
        assert access.can_view() is True
        assert access.can_control() is True
        assert access.can_manage_access() is True


# ============================================================================
# ДОПОЛНИТЕЛЬНЫЕ ИНТЕГРАЦИОННЫЕ ТЕСТЫ
# ============================================================================

class TestModelsJSONDeserialization:
    """Тесты десериализации моделей из JSON."""

    def test_ha_source_from_json(self, valid_ha_source_data):
        """Создание HASource из JSON."""
        source = HASource(**valid_ha_source_data)
        json_data = json.loads(source.model_dump_json())

        source_from_json = HASource(**json_data)
        assert source_from_json.name == source.name
        assert str(source_from_json.url) == str(source.url)

    def test_device_from_json(self, valid_device_data):
        """Создание Device из JSON."""
        device = Device(**valid_device_data)
        json_data = json.loads(device.model_dump_json())

        device_from_json = Device(**json_data)
        assert device_from_json.ha_entity_id == device.ha_entity_id
        assert device_from_json.device_type == device.device_type

    def test_device_config_from_json(self, valid_device_config_data):
        """Создание DeviceConfig из JSON."""
        config = DeviceConfig(**valid_device_config_data)
        json_data = json.loads(config.model_dump_json())

        config_from_json = DeviceConfig(**json_data)
        assert config_from_json.display_name == config.display_name
        assert config_from_json.tags == config.tags

    def test_device_command_from_json(self, valid_device_command_data):
        """Создание DeviceCommand из JSON."""
        command = DeviceCommand(**valid_device_command_data)
        json_data = json.loads(command.model_dump_json())

        command_from_json = DeviceCommand(**json_data)
        assert command_from_json.name == command.name
        assert command_from_json.ha_service == command.ha_service

    def test_device_access_from_json(self, valid_device_access_data):
        """Создание DeviceAccess из JSON."""
        access = DeviceAccess(**valid_device_access_data)
        json_data = json.loads(access.model_dump_json())

        access_from_json = DeviceAccess(**json_data)
        assert access_from_json.user_id == access.user_id
        assert access_from_json.role == access.role


class TestCommandExecutionModels:
    """Тесты моделей для выполнения команд."""

    def test_command_execution_request_создание(self):
        """Создание CommandExecutionRequest."""
        request = CommandExecutionRequest(
            name="turn_on",
            parameters={"brightness": 200}
        )

        assert request.name == "turn_on"
        assert request.parameters["brightness"] == 200

    def test_command_execution_response_создание(self):
        """Создание CommandExecutionResponse."""
        response = CommandExecutionResponse(
            id=uuid4(),
            device_id=uuid4(),
            command_name="turn_on",
            status="success",
            result={"state": "on"}
        )

        assert response.command_name == "turn_on"
        assert response.status == "success"
        assert response.result["state"] == "on"


class TestModelsUUIDHandling:
    """Тесты обработки UUID в моделях."""

    def test_ha_source_автогенерирует_uuid(self):
        """HASource автогенерирует UUID."""
        source1 = HASource(
            name="Test1",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        source2 = HASource(
            name="Test2",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )

        assert source1.id != source2.id

    def test_device_с_явным_uuid(self):
        """Device принимает явный UUID."""
        test_id = uuid4()
        device = Device(
            id=test_id,
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light"
        )

        assert device.id == test_id


class TestModelsTimestamps:
    """Тесты обработки временных меток в моделях."""

    def test_ha_source_созданы_временные_метки(self):
        """HASource создаёт временные метки."""
        before = datetime.utcnow()
        source = HASource(
            name="Test",
            url="http://localhost:8123",
            token="token_min_10_chars_here"
        )
        after = datetime.utcnow()

        assert before <= source.created_at <= after
        assert before <= source.updated_at <= after

    def test_device_config_созданы_временные_метки(self):
        """DeviceConfig создаёт временные метки."""
        before = datetime.utcnow()
        config = DeviceConfig(device_id=uuid4())
        after = datetime.utcnow()

        assert before <= config.created_at <= after
        assert before <= config.updated_at <= after


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_device_с_пустым_state(self):
        """Device с пустым состоянием."""
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=uuid4(),
            name="Test",
            device_type="light",
            state={}
        )
        assert device.state == {}

    def test_device_config_с_пустыми_тегами(self):
        """DeviceConfig с пустым списком тегов."""
        config = DeviceConfig(
            device_id=uuid4(),
            tags=[]
        )
        assert config.tags == []

    def test_device_command_с_пустыми_параметрами(self):
        """DeviceCommand с пустыми параметрами."""
        command = DeviceCommand(
            device_id=uuid4(),
            name="test",
            ha_service="light.turn_on",
            parameters={}
        )
        assert command.parameters == {}

    def test_device_access_с_длинными_id(self):
        """DeviceAccess с длинными идентификаторами."""
        long_user_id = "user_" + "a" * 100
        access = DeviceAccess(
            device_id=uuid4(),
            user_id=long_user_id,
            role="viewer",
            granted_by="admin"
        )
        assert access.user_id == long_user_id


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
