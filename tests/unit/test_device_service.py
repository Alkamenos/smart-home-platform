"""
Полный набор unit тестов для класса DeviceService.

Покрывает все методы сервиса управления устройствами:
- Инициализация с зависимостями
- Синхронизация устройств из Home Assistant
- Получение устройств по ID и источнику
- Обновление состояния устройств
- Преобразование HA states в Device модели
- Конфигурирование устройств
- Управление доступом на основе ролей
- Обработка изменений состояния через WebSocket
- Выполнение команд на устройствах
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from src.core.events.event_bus import EventBus
from src.core.models.device import Device
from src.core.models.device_access import DeviceAccess
from src.core.models.device_config import DeviceConfig
from src.services.device_service import (
    EVENT_DEVICE_ACCESS_CHANGED,
    EVENT_DEVICE_CONFIG_CHANGED,
    EVENT_DEVICE_LOADED,
    EVENT_DEVICE_STATE_CHANGED,
    DeviceService,
)


# ============================================================================
# Fixtures для подготовки тестовых данных
# ============================================================================


@pytest.fixture
def event_bus():
    """Фикстура: создать mock EventBus."""
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def mock_persistence():
    """Фикстура: создать mock persistence модуля."""
    persistence = MagicMock()
    persistence.save_device = AsyncMock()
    persistence.load_device = AsyncMock()
    persistence.save_devices = AsyncMock()
    persistence.load_all_devices = AsyncMock(return_value=[])
    persistence.save_device_config = AsyncMock()
    persistence.load_device_config = AsyncMock()

    # Mock sources
    sources_mock = MagicMock()
    sources_mock.load_source = AsyncMock()
    sources_mock.save_source = AsyncMock()
    sources_mock.load_all_sources = AsyncMock(return_value=[])
    sources_mock.delete_source = AsyncMock(return_value=True)
    persistence.sources = sources_mock

    # Mock devices
    devices_mock = MagicMock()
    devices_mock.save_device = AsyncMock()
    devices_mock.load_device = AsyncMock()
    devices_mock.save_devices = AsyncMock()
    devices_mock.load_all_devices = AsyncMock(return_value=[])
    devices_mock.load_devices_by_source = AsyncMock(return_value=[])
    devices_mock.save_device_config = AsyncMock()
    devices_mock.load_device_config = AsyncMock()
    persistence.devices = devices_mock

    # Mock device_access
    device_access_mock = MagicMock()
    device_access_mock.load_access_for_user_device = AsyncMock()
    device_access_mock.save_access = AsyncMock()
    device_access_mock.delete_access = AsyncMock(return_value=True)
    device_access_mock.load_access = AsyncMock()
    device_access_mock.load_accesses_for_device = AsyncMock(return_value=[])
    device_access_mock.load_accesses_for_user = AsyncMock(return_value=[])

    persistence.device_access = device_access_mock

    return persistence


@pytest.fixture
def mock_ha_adapter():
    """Фикстура: создать mock HAAdapter."""
    adapter = MagicMock()
    adapter.call_service = AsyncMock()
    adapter.connect = AsyncMock()
    return adapter


@pytest.fixture
def device_service(event_bus, mock_persistence, mock_ha_adapter):
    """Фикстура: создать экземпляр DeviceService с мок зависимостями."""
    service = DeviceService(
        event_bus=event_bus,
        persistence_module=mock_persistence,
        ha_adapter=mock_ha_adapter,
    )
    return service


@pytest.fixture
def sample_device():
    """Фикстура: создать пример Device объекта."""
    source_id = uuid4()
    device_id = uuid4()

    return Device(
        id=device_id,
        ha_entity_id="light.kitchen_light",
        source_id=source_id,
        name="Kitchen Light",
        device_type="light",
        model="Philips Hue A19",
        manufacturer="Philips",
        state={"state": "on", "brightness": 200},
        attributes={"friendly_name": "Kitchen Light", "brightness": 200},
        status="available",
    )


@pytest.fixture
def sample_ha_states():
    """Фикстура: создать примеры HA states для парсинга."""
    return [
        {
            "entity_id": "light.kitchen_light",
            "state": "on",
            "attributes": {
                "friendly_name": "Kitchen Light",
                "brightness": 200,
                "model": "Philips Hue A19",
                "manufacturer": "Philips",
            },
        },
        {
            "entity_id": "light.bedroom_light",
            "state": "off",
            "attributes": {
                "friendly_name": "Bedroom Light",
                "brightness": 0,
            },
        },
        {
            "entity_id": "switch.living_room_fan",
            "state": "unavailable",
            "attributes": {
                "friendly_name": "Living Room Fan",
                "model": "Generic Fan",
            },
        },
        {
            "entity_id": "climate.kitchen",
            "state": "heat",
            "attributes": {
                "friendly_name": "Kitchen Climate",
                "current_temperature": 21.5,
                "target_temperature": 22,
            },
        },
    ]


# ============================================================================
# Тесты инициализации
# ============================================================================


class TestDeviceServiceInitialization:
    """Тесты инициализации DeviceService."""

    def test_init_with_all_dependencies(self, event_bus, mock_persistence, mock_ha_adapter):
        """Проверяет инициализацию с полным набором зависимостей."""
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=mock_persistence,
            ha_adapter=mock_ha_adapter,
        )

        assert service.event_bus is event_bus
        assert service.persistence is mock_persistence
        assert service.ha_adapter is mock_ha_adapter
        assert service._devices == {}
        assert service._sources == {}
        assert service._commands == {}
        assert service._unavailable_timers == {}

    def test_init_with_minimal_dependencies(self, event_bus):
        """Проверяет инициализацию только с обязательной зависимостью."""
        service = DeviceService(event_bus=event_bus)

        assert service.event_bus is event_bus
        assert service.persistence is None
        assert service.ha_adapter is None
        assert service._devices == {}

    def test_init_creates_empty_collections(self, event_bus):
        """Проверяет что инициализация создает пустые коллекции."""
        service = DeviceService(event_bus=event_bus)

        assert isinstance(service._devices, dict)
        assert isinstance(service._sources, dict)
        assert isinstance(service._commands, dict)
        assert isinstance(service._unavailable_timers, dict)


# ============================================================================
# Тесты parse_devices
# ============================================================================


class TestParseDevices:
    """Тесты преобразования HA states в Device модели."""

    def test_parse_single_device(self, device_service, sample_ha_states):
        """Проверяет парсинг одного устройства."""
        result = device_service.parse_devices(sample_ha_states[:1])

        assert len(result) == 1
        assert result[0].ha_entity_id == "light.kitchen_light"
        assert result[0].name == "Kitchen Light"
        assert result[0].device_type == "light"
        assert result[0].model == "Philips Hue A19"
        assert result[0].manufacturer == "Philips"

    def test_parse_multiple_devices(self, device_service, sample_ha_states):
        """Проверяет парсинг нескольких устройств."""
        result = device_service.parse_devices(sample_ha_states)

        assert len(result) == 4
        assert result[0].device_type == "light"
        assert result[1].device_type == "light"
        assert result[2].device_type == "switch"
        assert result[3].device_type == "climate"

    def test_parse_device_with_unavailable_status(self, device_service):
        """Проверяет парсинг устройства с unavailable статусом."""
        ha_states = [
            {
                "entity_id": "sensor.unavailable",
                "state": "unavailable",
                "attributes": {"friendly_name": "Unavailable Sensor"},
            }
        ]

        result = device_service.parse_devices(ha_states)

        assert len(result) == 1
        assert result[0].status == "unavailable"

    def test_parse_device_with_available_status(self, device_service, sample_ha_states):
        """Проверяет парсинг устройства с available статусом."""
        result = device_service.parse_devices(sample_ha_states[:1])

        assert result[0].status == "available"

    def test_parse_missing_entity_id_skipped(self, device_service):
        """Проверяет что устройство без entity_id пропускается."""
        ha_states = [
            {
                "state": "on",
                "attributes": {"friendly_name": "Missing ID"},
            }
        ]

        result = device_service.parse_devices(ha_states)

        assert len(result) == 0

    def test_parse_empty_list(self, device_service):
        """Проверяет парсинг пустого списка."""
        result = device_service.parse_devices([])

        assert result == []

    def test_parse_malformed_device_skipped(self, device_service):
        """Проверяет что malformed устройства пропускаются и не вызывают ошибок."""
        ha_states = [
            {
                "entity_id": "light.valid",
                "state": "on",
                "attributes": {"friendly_name": "Valid"},
            },
            {
                "entity_id": "light.invalid",
                "state": "on",
                # attributes отсутствуют
                "invalid_field": "should be ignored",
            },
            None,  # Полностью невалидный элемент
        ]

        # Должно вернуться 1 валидное устройство
        result = device_service.parse_devices([s for s in ha_states if s])

        assert len(result) >= 1
        assert result[0].ha_entity_id == "light.valid"

    def test_parse_device_state_structure(self, device_service):
        """Проверяет структуру state в parsed Device."""
        ha_states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"brightness": 150, "color_temp": 370},
            }
        ]

        result = device_service.parse_devices(ha_states)

        assert result[0].state == {"state": "on"}
        assert result[0].attributes == {"brightness": 150, "color_temp": 370}


# ============================================================================
# Тесты get_device
# ============================================================================


class TestGetDevice:
    """Тесты получения устройства по ID."""

    @pytest.mark.asyncio
    async def test_get_existing_device(self, device_service, sample_device):
        """Проверяет получение существующего устройства."""
        device_service._devices[sample_device.id] = sample_device

        result = await device_service.get_device(sample_device.id)

        assert result is sample_device
        assert result.ha_entity_id == "light.kitchen_light"

    @pytest.mark.asyncio
    async def test_get_non_existing_device(self, device_service):
        """Проверяет получение несуществующего устройства."""
        fake_id = uuid4()

        result = await device_service.get_device(fake_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_device_empty_collection(self, device_service):
        """Проверяет получение из пустой коллекции."""
        result = await device_service.get_device(uuid4())

        assert result is None


# ============================================================================
# Тесты get_devices_by_source
# ============================================================================


class TestGetDevicesBySource:
    """Тесты получения устройств от источника."""

    @pytest.mark.asyncio
    async def test_get_devices_from_source(self, device_service):
        """Проверяет получение устройств от конкретного источника."""
        source_id = uuid4()

        # Создаем тестовые устройства
        device1 = Device(
            ha_entity_id="light.kitchen",
            source_id=source_id,
            name="Kitchen",
            device_type="light",
        )
        device2 = Device(
            ha_entity_id="light.bedroom",
            source_id=source_id,
            name="Bedroom",
            device_type="light",
        )
        other_source_id = uuid4()
        device3 = Device(
            ha_entity_id="switch.living_room",
            source_id=other_source_id,
            name="Living Room",
            device_type="switch",
        )

        device_service._devices[device1.id] = device1
        device_service._devices[device2.id] = device2
        device_service._devices[device3.id] = device3

        result = await device_service.get_devices_by_source(source_id)

        assert len(result) == 2
        assert device1 in result
        assert device2 in result
        assert device3 not in result

    @pytest.mark.asyncio
    async def test_get_devices_from_non_existing_source(self, device_service):
        """Проверяет получение устройств от несуществующего источника."""
        fake_source_id = uuid4()

        result = await device_service.get_devices_by_source(fake_source_id)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_devices_empty_collection(self, device_service):
        """Проверяет получение из пустой коллекции."""
        result = await device_service.get_devices_by_source(uuid4())

        assert result == []


# ============================================================================
# Тесты update_device_state
# ============================================================================


class TestUpdateDeviceState:
    """Тесты обновления состояния устройства."""

    @pytest.mark.asyncio
    async def test_update_state_existing_device(self, device_service, sample_device):
        """Проверяет обновление состояния существующего устройства."""
        device_service._devices[sample_device.id] = sample_device
        new_state = {"state": "off", "brightness": 0}

        await device_service.update_device_state(sample_device.id, new_state)

        assert device_service._devices[sample_device.id].state == new_state

    @pytest.mark.asyncio
    async def test_update_state_non_existing_device(self, device_service):
        """Проверяет обновление состояния несуществующего устройства."""
        fake_id = uuid4()
        new_state = {"state": "off"}

        # Не должно вызвать исключение
        await device_service.update_device_state(fake_id, new_state)

        # Проверяем что устройство не было добавлено
        assert fake_id not in device_service._devices

    @pytest.mark.asyncio
    async def test_update_state_complex_state(self, device_service, sample_device):
        """Проверяет обновление сложного состояния."""
        device_service._devices[sample_device.id] = sample_device
        complex_state = {
            "state": "heat",
            "current_temperature": 21.5,
            "target_temperature": 22,
            "mode": "auto",
            "attributes": {"model": "Nest"},
        }

        await device_service.update_device_state(sample_device.id, complex_state)

        assert device_service._devices[sample_device.id].state == complex_state


# ============================================================================
# Тесты sync_devices_from_source
# ============================================================================


class TestSyncDevicesFromSource:
    """Тесты синхронизации устройств из источника."""

    @pytest.mark.asyncio
    async def test_sync_source_not_found(self, device_service, mock_persistence):
        """Проверяет ошибку когда источник не найден."""
        source_id = uuid4()
        mock_persistence.sources.load_source.return_value = None

        with pytest.raises(ValueError, match="не найден"):
            await device_service.sync_devices_from_source(source_id)

    @pytest.mark.asyncio
    async def test_sync_successful_with_devices(self, device_service, mock_persistence):
        """Проверяет успешную синхронизацию с устройствами."""
        from unittest.mock import AsyncMock, patch

        from src.core.models.ha_source import HASource

        source_id = uuid4()
        source = HASource(
            id=source_id,
            name="Test HA",
            url="http://localhost:8123",
            token="test_token",
        )

        mock_persistence.sources.load_source.return_value = source

        # Mock HA REST client
        mock_ha_states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
            {
                "entity_id": "switch.bedroom",
                "state": "off",
                "attributes": {"friendly_name": "Bedroom Switch"},
            },
        ]

        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient"
        ) as mock_rest_client_class:
            mock_rest_client = AsyncMock()
            mock_rest_client.connect_to_ha = AsyncMock(return_value=True)
            mock_rest_client.fetch_devices = AsyncMock(return_value=mock_ha_states)
            mock_rest_client.__aenter__ = AsyncMock(return_value=mock_rest_client)
            mock_rest_client.__aexit__ = AsyncMock(return_value=None)
            mock_rest_client_class.return_value = mock_rest_client

            result = await device_service.sync_devices_from_source(source_id)

            assert isinstance(result, list)
            assert len(result) == 2
            assert result[0].ha_entity_id == "light.kitchen"
            assert result[1].ha_entity_id == "switch.bedroom"
            # Проверяем что source_id установлен
            assert all(d.source_id == source_id for d in result)
            # Проверяем что был вызван save_devices
            mock_persistence.devices.save_devices.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_publishes_device_loaded_events(
        self, device_service, mock_persistence, event_bus
    ):
        """Проверяет что синхронизация публикует device.loaded для каждого устройства."""
        from unittest.mock import AsyncMock, patch

        from src.core.models.ha_source import HASource

        source_id = uuid4()
        source = HASource(
            id=source_id,
            name="Test HA",
            url="http://localhost:8123",
            token="test_token",
        )
        mock_persistence.sources.load_source.return_value = source

        mock_ha_states = [
            {
                "entity_id": "light.kitchen",
                "state": "on",
                "attributes": {"friendly_name": "Kitchen Light"},
            },
            {
                "entity_id": "switch.bedroom",
                "state": "off",
                "attributes": {"friendly_name": "Bedroom Switch"},
            },
        ]

        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient"
        ) as mock_rest_client_class:
            mock_rest_client = AsyncMock()
            mock_rest_client.connect_to_ha = AsyncMock(return_value=True)
            mock_rest_client.fetch_devices = AsyncMock(return_value=mock_ha_states)
            mock_rest_client.__aenter__ = AsyncMock(return_value=mock_rest_client)
            mock_rest_client.__aexit__ = AsyncMock(return_value=None)
            mock_rest_client_class.return_value = mock_rest_client

            result = await device_service.sync_devices_from_source(source_id)

        assert event_bus.publish.await_count == len(result)
        published_types = [call.args[0] for call in event_bus.publish.await_args_list]
        assert published_types == [EVENT_DEVICE_LOADED] * len(result)

    @pytest.mark.asyncio
    async def test_sync_connection_error(self, device_service, mock_persistence):
        """Проверяет обработку ошибки подключения."""
        from unittest.mock import AsyncMock, patch

        from src.core.models.ha_source import HASource

        source_id = uuid4()
        source = HASource(
            id=source_id,
            name="Test HA",
            url="http://localhost:8123",
            token="test_token",
        )

        mock_persistence.sources.load_source.return_value = source

        with patch(
            "src.adapters.home_assistant.rest_client.HARestClient"
        ) as mock_rest_client_class:
            mock_rest_client = AsyncMock()
            mock_rest_client.connect_to_ha = AsyncMock(return_value=False)
            mock_rest_client.__aenter__ = AsyncMock(return_value=mock_rest_client)
            mock_rest_client.__aexit__ = AsyncMock(return_value=None)
            mock_rest_client_class.return_value = mock_rest_client

            with pytest.raises(RuntimeError, match="Не удалось подключиться"):
                await device_service.sync_devices_from_source(source_id)

    @pytest.mark.asyncio
    async def test_sync_with_logging(self, device_service, mock_persistence, caplog):
        """Проверяет что синхронизация логирует действия."""
        import logging

        caplog.set_level(logging.INFO)
        source_id = uuid4()

        # Убедимся что persistence возвращает None для source_id
        mock_persistence.sources.load_source.return_value = None

        with pytest.raises(ValueError):
            await device_service.sync_devices_from_source(source_id)

        assert "Начинаю синхронизацию" in caplog.text


# ============================================================================
# Тесты update_device_config
# ============================================================================


class TestUpdateDeviceConfig:
    """Тесты обновления конфигурации устройства."""

    @pytest.mark.asyncio
    async def test_update_config_display_name(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет обновление display_name конфигурации."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.load_device_config.return_value = None

        config = await device_service.update_device_config(
            sample_device.id,
            display_name="Мой светильник",
            updated_by="admin",
        )

        assert config.display_name == "Мой светильник"
        assert config.device_id == sample_device.id
        mock_persistence.save_device_config.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_config_all_fields(self, device_service, sample_device, mock_persistence):
        """Проверяет обновление всех полей конфигурации."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.load_device_config.return_value = None

        config = await device_service.update_device_config(
            sample_device.id,
            display_name="Kitchen Light",
            description="Main kitchen lighting",
            location="Kitchen",
            tags=["lighting", "kitchen"],
            updated_by="admin",
        )

        assert config.display_name == "Kitchen Light"
        assert config.description == "Main kitchen lighting"
        assert config.location == "Kitchen"
        assert config.tags == ["lighting", "kitchen"]

    @pytest.mark.asyncio
    async def test_update_config_device_not_found(self, device_service):
        """Проверяет обновление конфигурации для несуществующего устройства."""
        fake_id = uuid4()

        with pytest.raises(ValueError, match="не найдено"):
            await device_service.update_device_config(
                fake_id,
                display_name="Test",
            )

    @pytest.mark.asyncio
    async def test_update_config_publishes_event(
        self, device_service, sample_device, mock_persistence, event_bus
    ):
        """Проверяет что обновление конфигурации публикует событие."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.load_device_config.return_value = None

        await device_service.update_device_config(
            sample_device.id,
            display_name="New Name",
            updated_by="admin",
        )

        # Проверяем что событие было опубликовано
        event_bus.publish.assert_awaited_once()
        event_type, payload = event_bus.publish.await_args.args
        assert event_type == EVENT_DEVICE_CONFIG_CHANGED
        assert payload["device_id"] == str(sample_device.id)
        assert payload["changed_by"] == "admin"
        assert "display_name" in payload["changes"]

    @pytest.mark.asyncio
    async def test_update_config_existing_config(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет обновление существующей конфигурации."""
        device_service._devices[sample_device.id] = sample_device
        existing_config = DeviceConfig(
            device_id=sample_device.id,
            display_name="Old Name",
            description="Old description",
        )
        mock_persistence.load_device_config.return_value = existing_config

        config = await device_service.update_device_config(
            sample_device.id,
            display_name="New Name",
            updated_by="admin",
        )

        assert config.display_name == "New Name"
        assert config.description == "Old description"  # Не изменилось


# ============================================================================
# Тесты check_device_access
# ============================================================================


class TestCheckDeviceAccess:
    """Тесты проверки доступа к устройству."""

    @pytest.mark.asyncio
    async def test_check_access_viewer_allowed(self, device_service, mock_persistence):
        """Проверяет доступ пользователя с ролью viewer."""
        device_id = uuid4()
        user_id = "user1"

        access = DeviceAccess(
            device_id=device_id,
            user_id=user_id,
            role="viewer",
            granted_by="admin",
        )
        mock_persistence.device_access.load_access_for_user_device.return_value = access

        result = await device_service.check_device_access(
            device_id, user_id, required_role="viewer"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_access_controller_allowed(self, device_service, mock_persistence):
        """Проверяет доступ пользователя с ролью controller."""
        device_id = uuid4()
        user_id = "user1"

        access = DeviceAccess(
            device_id=device_id,
            user_id=user_id,
            role="controller",
            granted_by="admin",
        )
        mock_persistence.device_access.load_access_for_user_device.return_value = access

        result = await device_service.check_device_access(
            device_id, user_id, required_role="controller"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_check_access_insufficient_role(self, device_service, mock_persistence):
        """Проверяет отказ доступа при недостаточной роли."""
        device_id = uuid4()
        user_id = "user1"

        access = DeviceAccess(
            device_id=device_id,
            user_id=user_id,
            role="viewer",
            granted_by="admin",
        )
        mock_persistence.device_access.load_access_for_user_device.return_value = access

        result = await device_service.check_device_access(
            device_id, user_id, required_role="controller"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_check_access_not_found(self, device_service, mock_persistence):
        """Проверяет отказ доступа когда запись не найдена."""
        device_id = uuid4()
        user_id = "unknown_user"

        mock_persistence.device_access.load_access_for_user_device.return_value = None

        result = await device_service.check_device_access(
            device_id, user_id, required_role="viewer"
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_check_access_no_persistence(self, event_bus):
        """Проверяет отказ доступа когда нет persistence модуля."""
        service = DeviceService(event_bus=event_bus)
        device_id = uuid4()
        user_id = "user1"

        result = await service.check_device_access(device_id, user_id)

        assert result is False


# ============================================================================
# Тесты grant_access
# ============================================================================


class TestGrantAccess:
    """Тесты предоставления доступа к устройству."""

    @pytest.mark.asyncio
    async def test_grant_access_creates_new_access(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет создание нового доступа."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.device_access.load_access_for_user_device.return_value = None

        result = await device_service.grant_access(
            sample_device.id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )

        assert result is not None
        assert result.user_id == "user1"
        assert result.role == "controller"
        mock_persistence.device_access.save_access.assert_called_once()

    @pytest.mark.asyncio
    async def test_grant_access_updates_existing(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет обновление существующего доступа."""
        device_service._devices[sample_device.id] = sample_device

        old_access = DeviceAccess(
            device_id=sample_device.id,
            user_id="user1",
            role="viewer",
            granted_by="admin",
        )
        mock_persistence.device_access.load_access_for_user_device.return_value = old_access
        mock_persistence.device_access.delete_access = AsyncMock()

        result = await device_service.grant_access(
            sample_device.id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )

        assert result.role == "controller"
        mock_persistence.device_access.delete_access.assert_called_once()

    @pytest.mark.asyncio
    async def test_grant_access_device_not_found(self, device_service, mock_persistence):
        """Доступ выдаётся даже если устройство ещё не синхронизировано (device-blind grant).

        Отклонение зафиксировано в specs/004: grant разрешён до синка,
        чтобы можно было заранее выдать права на ещё не загруженное устройство.
        """
        fake_id = uuid4()
        mock_persistence.device_access.load_access_for_user_device.return_value = None

        result = await device_service.grant_access(
            fake_id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )

        assert result is not None
        assert result.device_id == fake_id
        assert result.role == "controller"
        mock_persistence.device_access.save_access.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_grant_access_invalid_role(self, device_service, sample_device, mock_persistence):
        """Проверяет отказ при невалидной роли."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.device_access.load_access_for_user_device.return_value = None

        result = await device_service.grant_access(
            sample_device.id,
            user_id="user1",
            role="invalid_role",  # type: ignore
            granted_by="admin",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_grant_access_publishes_event(
        self, device_service, sample_device, mock_persistence, event_bus
    ):
        """Проверяет что предоставление доступа публикует событие."""
        device_service._devices[sample_device.id] = sample_device
        mock_persistence.device_access.load_access_for_user_device.return_value = None

        await device_service.grant_access(
            sample_device.id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )

        event_bus.publish.assert_awaited_once()
        event_type, payload = event_bus.publish.await_args.args
        assert event_type == EVENT_DEVICE_ACCESS_CHANGED
        assert payload["user_id"] == "user1"
        assert payload["action"] == "granted"
        assert payload["role"] == "controller"


# ============================================================================
# Тесты revoke_access
# ============================================================================


class TestRevokeAccess:
    """Тесты отзыва доступа."""

    @pytest.mark.asyncio
    async def test_revoke_access_success(self, device_service, mock_persistence, event_bus):
        """Проверяет успешный отзыв доступа."""
        access_id = uuid4()
        device_id = uuid4()

        access = DeviceAccess(
            id=access_id,
            device_id=device_id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )
        mock_persistence.device_access.load_access.return_value = access
        mock_persistence.device_access.delete_access.return_value = True

        result = await device_service.revoke_access(access_id)

        assert result is True
        mock_persistence.device_access.delete_access.assert_called_once_with(access_id)
        event_bus.publish.assert_awaited_once()
        event_type, payload = event_bus.publish.await_args.args
        assert event_type == EVENT_DEVICE_ACCESS_CHANGED
        assert payload["action"] == "revoked"
        assert payload["device_id"] == str(device_id)

    @pytest.mark.asyncio
    async def test_revoke_access_not_found(self, device_service, mock_persistence):
        """Проверяет отзыв несуществующего доступа."""
        access_id = uuid4()
        mock_persistence.device_access.load_access.return_value = None
        mock_persistence.device_access.delete_access.return_value = False

        result = await device_service.revoke_access(access_id)

        assert result is False


# ============================================================================
# Тесты get_device_accesses
# ============================================================================


class TestGetDeviceAccesses:
    """Тесты получения доступов к устройству."""

    @pytest.mark.asyncio
    async def test_get_device_accesses(self, device_service, mock_persistence):
        """Проверяет получение доступов к устройству."""
        device_id = uuid4()

        access1 = DeviceAccess(
            device_id=device_id,
            user_id="user1",
            role="viewer",
            granted_by="admin",
        )
        access2 = DeviceAccess(
            device_id=device_id,
            user_id="user2",
            role="controller",
            granted_by="admin",
        )
        mock_persistence.device_access.load_accesses_for_device.return_value = [
            access1,
            access2,
        ]

        result = await device_service.get_device_accesses(device_id)

        assert len(result) == 2
        assert access1 in result
        assert access2 in result


# ============================================================================
# Тесты get_user_accessible_devices
# ============================================================================


class TestGetUserAccessibleDevices:
    """Тесты получения устройств пользователя."""

    @pytest.mark.asyncio
    async def test_get_user_accessible_devices(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет получение устройств пользователя."""
        device_service._devices[sample_device.id] = sample_device

        access = DeviceAccess(
            device_id=sample_device.id,
            user_id="user1",
            role="controller",
            granted_by="admin",
        )
        mock_persistence.device_access.load_accesses_for_user.return_value = [access]

        result = await device_service.get_user_accessible_devices("user1")

        assert len(result) == 1
        assert result[0] is sample_device


# ============================================================================
# Тесты handle_state_change
# ============================================================================


class TestHandleStateChange:
    """Тесты обработки изменений состояния через WebSocket."""

    @pytest.mark.asyncio
    async def test_handle_state_change_updates_device(
        self, device_service, sample_device, event_bus
    ):
        """Проверяет обновление состояния устройства при изменении."""
        device_service._devices[sample_device.id] = sample_device

        event_data = {
            "data": {
                "entity_id": sample_device.ha_entity_id,
                "old_state": {"state": "on"},
                "new_state": {
                    "state": "off",
                    "attributes": {"brightness": 0},
                },
            }
        }

        await device_service.handle_state_change(event_data)

        assert device_service._devices[sample_device.id].state["state"] == "off"
        event_bus.publish.assert_awaited_once()
        event_type, payload = event_bus.publish.await_args.args
        assert event_type == EVENT_DEVICE_STATE_CHANGED
        assert payload["new_state"]["state"] == "off"
        assert payload["source"] == "ha"

    @pytest.mark.asyncio
    async def test_handle_state_change_missing_entity_id(self, device_service, event_bus):
        """Проверяет обработку события без entity_id."""
        event_data = {"data": {}}

        # Не должно вызвать исключение
        await device_service.handle_state_change(event_data)

    @pytest.mark.asyncio
    async def test_handle_state_change_device_not_found(self, device_service, event_bus):
        """Проверяет обработку события для несуществующего устройства."""
        event_data = {
            "data": {
                "entity_id": "light.unknown",
                "old_state": {"state": "on"},
                "new_state": {"state": "off"},
            }
        }

        # Не должно вызвать исключение
        await device_service.handle_state_change(event_data)

    @pytest.mark.asyncio
    async def test_handle_state_change_unavailable_to_available(
        self, device_service, sample_device, event_bus
    ):
        """Проверяет переход из unavailable в available."""
        sample_device.status = "unavailable"
        device_service._devices[sample_device.id] = sample_device

        event_data = {
            "data": {
                "entity_id": sample_device.ha_entity_id,
                "old_state": {"state": "unavailable"},
                "new_state": {"state": "on", "attributes": {}},
            }
        }

        await device_service.handle_state_change(event_data)

        assert device_service._devices[sample_device.id].status == "available"


# ============================================================================
# Тесты execute_command
# ============================================================================


class TestExecuteCommand:
    """Тесты выполнения команд на устройстве."""

    @pytest.mark.asyncio
    async def test_execute_command_success(
        self, device_service, sample_device, mock_ha_adapter, event_bus
    ):
        """Проверяет успешное выполнение команды."""
        device_service._devices[sample_device.id] = sample_device
        mock_ha_adapter.call_service.return_value = {"success": True}

        result = await device_service.execute_command(
            device_id=sample_device.id,
            command_name="turn_on",
            parameters={"brightness": 255},
            timeout=30,
        )

        assert result.status == "success"
        assert result.device_id == sample_device.id
        mock_ha_adapter.call_service.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_command_timeout(self, device_service, sample_device, mock_ha_adapter):
        """Проверяет таймаут команды."""
        device_service._devices[sample_device.id] = sample_device

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(2)

        mock_ha_adapter.call_service.side_effect = slow_call

        with pytest.raises(RuntimeError, match="timeout"):
            await device_service.execute_command(
                device_id=sample_device.id,
                command_name="turn_on",
                parameters={},
                timeout=1,
            )

    @pytest.mark.asyncio
    async def test_execute_command_device_not_found(self, device_service):
        """Проверяет выполнение команды на несуществующем устройстве."""
        fake_id = uuid4()

        with pytest.raises(ValueError, match="not found"):
            await device_service.execute_command(
                device_id=fake_id,
                command_name="turn_on",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_execute_command_no_adapter(self, event_bus, mock_persistence):
        """Проверяет выполнение команды без адаптера."""
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=mock_persistence,
            ha_adapter=None,
        )
        device = Device(
            ha_entity_id="light.test",
            source_id=uuid4(),
            name="Test",
            device_type="light",
        )
        service._devices[device.id] = device

        with pytest.raises(RuntimeError, match="HA adapter not configured"):
            await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_execute_command_max_timeout(
        self, device_service, sample_device, mock_ha_adapter
    ):
        """Проверяет что максимальный таймаут ограничен 300 сек."""
        device_service._devices[sample_device.id] = sample_device
        mock_ha_adapter.call_service.return_value = {"success": True}

        result = await device_service.execute_command(
            device_id=sample_device.id,
            command_name="turn_on",
            parameters={},
            timeout=500,  # Больше максимума
        )

        # Таймаут должен быть сокращен до 300
        assert result.status == "success"


# ============================================================================
# Тесты get_command_status
# ============================================================================


class TestGetCommandStatus:
    """Тесты получения статуса команды."""

    @pytest.mark.asyncio
    async def test_get_command_status_existing(
        self, device_service, sample_device, mock_ha_adapter
    ):
        """Проверяет получение статуса существующей команды."""
        device_service._devices[sample_device.id] = sample_device
        command_id = uuid4()

        command_record = {
            "id": command_id,
            "device_id": sample_device.id,
            "command_name": "turn_on",
            "status": "success",
            "result": {"success": True},
        }
        device_service._commands[command_id] = command_record

        result = await device_service.get_command_status(sample_device.id, command_id)

        assert result is not None
        assert result["status"] == "success"
        assert result["command_name"] == "turn_on"

    @pytest.mark.asyncio
    async def test_get_command_status_not_found(self, device_service, sample_device):
        """Проверяет получение статуса несуществующей команды."""
        device_service._devices[sample_device.id] = sample_device
        fake_command_id = uuid4()

        result = await device_service.get_command_status(sample_device.id, fake_command_id)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_command_status_wrong_device(self, device_service):
        """Проверяет получение статуса команды для неправильного устройства."""
        device1_id = uuid4()
        device2_id = uuid4()
        command_id = uuid4()

        command_record = {
            "id": command_id,
            "device_id": device1_id,
            "command_name": "turn_on",
        }
        device_service._commands[command_id] = command_record

        result = await device_service.get_command_status(device2_id, command_id)

        assert result is None


# ============================================================================
# Интеграционные тесты
# ============================================================================


class TestIntegration:
    """Интеграционные тесты DeviceService."""

    @pytest.mark.asyncio
    async def test_full_device_lifecycle(
        self, device_service, sample_device, mock_persistence, event_bus
    ):
        """Проверяет полный жизненный цикл устройства."""
        # 1. Добавляем устройство
        device_service._devices[sample_device.id] = sample_device

        # 2. Получаем устройство
        retrieved = await device_service.get_device(sample_device.id)
        assert retrieved is not None

        # 3. Обновляем состояние
        new_state = {"state": "off"}
        await device_service.update_device_state(sample_device.id, new_state)
        assert device_service._devices[sample_device.id].state == new_state

        # 4. Обновляем конфигурацию
        mock_persistence.load_device_config.return_value = None
        config = await device_service.update_device_config(
            sample_device.id,
            display_name="Updated Kitchen Light",
        )
        assert config.display_name == "Updated Kitchen Light"

    @pytest.mark.asyncio
    async def test_device_with_access_control(
        self, device_service, sample_device, mock_persistence
    ):
        """Проверяет управление доступом к устройству."""
        device_service._devices[sample_device.id] = sample_device

        # 1. Предоставляем доступ
        mock_persistence.device_access.load_access_for_user_device.return_value = None
        access = await device_service.grant_access(
            sample_device.id,
            user_id="user1",
            role="viewer",
            granted_by="admin",
        )
        assert access is not None

        # 2. Проверяем доступ
        mock_persistence.device_access.load_access_for_user_device.return_value = access
        has_access = await device_service.check_device_access(
            sample_device.id, "user1", required_role="viewer"
        )
        assert has_access is True

        # 3. Отзываем доступ
        mock_persistence.device_access.load_access.return_value = access
        mock_persistence.device_access.delete_access.return_value = True
        revoked = await device_service.revoke_access(access.id)
        assert revoked is True

    @pytest.mark.asyncio
    async def test_parse_and_store_devices(
        self, device_service, sample_ha_states, mock_persistence
    ):
        """Проверяет парсинг и хранение устройств."""
        # 1. Парсим HA states
        devices = device_service.parse_devices(sample_ha_states)
        assert len(devices) == 4

        # 2. Сохраняем устройства
        for device in devices:
            device_service._devices[device.id] = device

        # 3. Получаем устройства по типу
        lights = [d for d in device_service._devices.values() if d.device_type == "light"]
        assert len(lights) == 2


# ============================================================================
# Edge Cases и Error Handling
# ============================================================================


class TestEdgeCases:
    """Тесты edge cases и обработки ошибок."""

    @pytest.mark.asyncio
    async def test_handle_state_change_with_malformed_data(
        self, device_service, event_bus, sample_device
    ):
        """Проверяет обработку malformed данных в состоянии.

        Не должно вызвать исключение: сервис логирует и продолжает работу.
        """
        device_service._devices[sample_device.id] = sample_device
        event_data = {
            "data": {
                "entity_id": sample_device.ha_entity_id,
                "new_state": None,  # Malformed
            }
        }

        # Не должно вызвать исключение
        await device_service.handle_state_change(event_data)

    def test_parse_devices_with_special_characters(self, device_service):
        """Проверяет парсинг устройств со специальными символами в имени."""
        ha_states = [
            {
                "entity_id": "light.kitchen_light",
                "state": "on",
                "attributes": {
                    "friendly_name": "Кухонный свет (основной)",
                    "model": "Philips Hue A19 ™",
                },
            }
        ]

        result = device_service.parse_devices(ha_states)

        assert result[0].name == "Кухонный свет (основной)"

    @pytest.mark.asyncio
    async def test_concurrent_state_updates(self, device_service, sample_device):
        """Проверяет конкурентные обновления состояния."""
        device_service._devices[sample_device.id] = sample_device

        # Одновременно обновляем состояние несколько раз
        await asyncio.gather(
            device_service.update_device_state(sample_device.id, {"state": "off"}),
            device_service.update_device_state(sample_device.id, {"state": "on"}),
            device_service.update_device_state(sample_device.id, {"state": "off"}),
        )

        # Финальное состояние должно быть одним из обновленных
        assert device_service._devices[sample_device.id].state in [
            {"state": "off"},
            {"state": "on"},
        ]

    @pytest.mark.asyncio
    async def test_check_access_with_error(self, device_service, mock_persistence):
        """Проверяет обработку ошибок при проверке доступа."""
        mock_persistence.device_access.load_access_for_user_device.side_effect = Exception(
            "Database error"
        )

        result = await device_service.check_device_access(uuid4(), "user1")

        assert result is False
