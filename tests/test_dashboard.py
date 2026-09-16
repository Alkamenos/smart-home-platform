"""
Tests for Dashboard Integration - проверка создания и обновления сенсоров

Спецификация:
- DashboardIntegration создает сенсоры для мониторинга FSM
- При изменении состояния FSM обновляется соответствующий сенсор
- При переподключении к HA все сущности воссоздаются
- Поддерживаются разные типы фич (lighting, climate, ventilation)
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dashboard.dashboard import DashboardIntegration


class TestDashboardIntegrationInitialization:
    """Тесты инициализации DashboardIntegration"""

    def test_init_with_ha_adapter_and_event_bus(self):
        """Инициализация с адаптером HA и шиной событий"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration.ha is ha_adapter
        assert integration.event_bus is event_bus
        assert integration._created_entities == {}

    def test_subscribes_to_fsm_state_changed_event(self):
        """Подписка на событие изменения состояния FSM"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        event_bus.subscribe.assert_any_call("fsm.state.changed", integration._on_state_changed)

    def test_subscribes_to_ha_connected_event(self):
        """Подписка на событие подключения к HA"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        event_bus.subscribe.assert_any_call("ha.connected", integration._on_ha_connected)


class TestCreateFsmSensor:
    """Тесты создания сенсора FSM"""

    @pytest.mark.asyncio
    async def test_creates_sensor_with_correct_config(self):
        """Создание сенсора с правильной конфигурацией"""
        ha_adapter = AsyncMock()
        ha_adapter.call_service = AsyncMock(return_value=True)
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        result = await integration.create_fsm_sensor(
            fsm_id="light.kitchen_motion", name="Kitchen Motion Light", feature_type="lighting"
        )

        assert result is True
        ha_adapter.call_service.assert_called_once()
        call_args = ha_adapter.call_service.call_args
        assert call_args[1]["domain"] == "homeassistant"
        assert call_args[1]["service"] == "set_config"
        data = call_args[1]["data"]
        assert data["entity_id"] == "sensor.fsm_light.kitchen_motion"
        assert data["name"] == "Kitchen Motion Light"
        assert data["icon"] == "mdi:lightbulb"
        assert data["device_class"] == "enum"

    @pytest.mark.asyncio
    async def test_stores_created_entity_id(self):
        """Сохранение ID созданной сущности"""
        ha_adapter = AsyncMock()
        ha_adapter.call_service = AsyncMock(return_value=True)
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        await integration.create_fsm_sensor(
            fsm_id="climate.living_room", name="Living Room Climate", feature_type="climate"
        )

        assert "climate.living_room" in integration._created_entities
        assert (
            integration._created_entities["climate.living_room"] == "sensor.fsm_climate.living_room"
        )

    @pytest.mark.asyncio
    async def test_returns_false_when_ha_call_fails(self):
        """Возврат False при ошибке вызова HA"""
        ha_adapter = AsyncMock()
        ha_adapter.call_service = AsyncMock(return_value=False)
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        result = await integration.create_fsm_sensor(
            fsm_id="light.bedroom", name="Bedroom Light", feature_type="lighting"
        )

        assert result is False
        assert "light.bedroom" not in integration._created_entities

    @pytest.mark.asyncio
    async def test_uses_correct_icon_for_feature_type(self):
        """Использование правильной иконки для типа фичи"""
        ha_adapter = AsyncMock()
        ha_adapter.call_service = AsyncMock(return_value=True)
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        # Проверяем разные типы фич
        feature_icons = {
            "lighting": "mdi:lightbulb",
            "climate": "mdi:thermometer",
            "ventilation": "mdi:fan",
            "security": "mdi:shield",
            "unknown": "mdi:cog",
        }

        for feature_type, expected_icon in feature_icons.items():
            ha_adapter.call_service.reset_mock()
            await integration.create_fsm_sensor(
                fsm_id=f"test.{feature_type}",
                name=f"Test {feature_type}",
                feature_type=feature_type,
            )

            data = ha_adapter.call_service.call_args[1]["data"]
            assert data["icon"] == expected_icon


class TestUpdateFsmSensor:
    """Тесты обновления сенсора FSM"""

    @pytest.mark.asyncio
    async def test_updates_sensor_state(self):
        """Обновление состояния сенсора"""
        ha_adapter = AsyncMock()
        ha_adapter.is_connected = True
        ha_adapter.set_entity_state = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)
        integration._created_entities["light.kitchen"] = "sensor.fsm_light.kitchen"

        await integration._update_fsm_sensor(
            fsm_id="light.kitchen",
            state="ON_MOTION",
            event_data={
                "timestamp": "2024-01-01T10:00:00",
                "old_state": "OFF",
                "event": "motion_detected",
                "feature_type": "lighting",
            },
        )

        ha_adapter.set_entity_state.assert_called_once()
        call_args = ha_adapter.set_entity_state.call_args
        assert call_args[1]["entity_id"] == "sensor.fsm_light.kitchen"
        assert call_args[1]["state"] == "ON_MOTION"
        attributes = call_args[1]["attributes"]
        assert attributes["last_transition"] == "2024-01-01T10:00:00"
        assert attributes["previous_state"] == "OFF"
        assert attributes["trigger_event"] == "motion_detected"
        assert attributes["feature_type"] == "lighting"

    @pytest.mark.asyncio
    async def test_skips_update_if_entity_not_created(self):
        """Пропуск обновления если сущность не создана"""
        ha_adapter = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        await integration._update_fsm_sensor(fsm_id="nonexistent", state="ON", event_data={})

        ha_adapter.set_entity_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_update_if_ha_not_connected(self):
        """Пропуск обновления если HA не подключен"""
        ha_adapter = AsyncMock()
        ha_adapter.is_connected = False
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)
        integration._created_entities["light.kitchen"] = "sensor.fsm_light.kitchen"

        await integration._update_fsm_sensor(fsm_id="light.kitchen", state="ON", event_data={})

        ha_adapter.set_entity_state.assert_not_called()


class TestCreateStatusBinarySensor:
    """Тесты создания binary sensor статуса"""

    @pytest.mark.asyncio
    async def test_creates_binary_sensor(self):
        """Создание binary sensor"""
        ha_adapter = AsyncMock()
        ha_adapter.set_entity_state = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        result = await integration.create_status_binary_sensor(
            fsm_id="light.kitchen", name="Kitchen Light"
        )

        assert result is True
        ha_adapter.set_entity_state.assert_called_once()
        call_args = ha_adapter.set_entity_state.call_args
        assert call_args[1]["entity_id"] == "binary_sensor.fsm_light.kitchen_status"
        assert call_args[1]["state"] == "on"
        assert call_args[1]["attributes"]["friendly_name"] == "Kitchen Light Status"
        assert call_args[1]["attributes"]["device_class"] == "running"
        assert call_args[1]["attributes"]["icon"] == "mdi:check-circle"

    @pytest.mark.asyncio
    async def test_stores_status_entity_id(self):
        """Сохранение ID статусной сущности"""
        ha_adapter = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)

        await integration.create_status_binary_sensor(
            fsm_id="climate.bedroom", name="Bedroom Climate"
        )

        assert "climate.bedroom_status" in integration._created_entities
        assert (
            integration._created_entities["climate.bedroom_status"]
            == "binary_sensor.fsm_climate.bedroom_status"
        )


class TestOnHaConnected:
    """Тесты обработки события подключения к HA"""

    @pytest.mark.asyncio
    async def test_recreates_entities_on_connect(self):
        """Воссоздание сущностей при подключении"""
        ha_adapter = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)
        integration._created_entities = {
            "light.kitchen": "sensor.fsm_light.kitchen",
            "climate.bedroom": "sensor.fsm_climate.bedroom",
        }

        # Мокаем метод _recreate_all_entities
        with patch.object(
            integration, "_recreate_all_entities", new_callable=AsyncMock
        ) as mock_recreate:
            await integration._on_ha_connected({})

            mock_recreate.assert_called_once()


class TestGetIconForFeature:
    """Тесты получения иконок для фич"""

    def test_returns_icon_for_lighting(self):
        """Иконка для освещения"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration._get_icon_for_feature("lighting") == "mdi:lightbulb"

    def test_returns_icon_for_climate(self):
        """Иконка для климата"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration._get_icon_for_feature("climate") == "mdi:thermometer"

    def test_returns_icon_for_ventilation(self):
        """Иконка для вентиляции"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration._get_icon_for_feature("ventilation") == "mdi:fan"

    def test_returns_icon_for_security(self):
        """Иконка для безопасности"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration._get_icon_for_feature("security") == "mdi:shield"

    def test_returns_default_icon_for_unknown(self):
        """Иконка по умолчанию для неизвестного типа"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        assert integration._get_icon_for_feature("unknown") == "mdi:cog"
        assert integration._get_icon_for_feature("nonexistent") == "mdi:cog"


class TestGetStateOptions:
    """Тесты получения опций состояний"""

    def test_returns_options_for_lighting(self):
        """Опции для освещения"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        options = integration._get_state_options("lighting")
        assert "off" in options
        assert "on" in options
        assert "auto" in options

    def test_returns_options_for_climate(self):
        """Опции для климата"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        options = integration._get_state_options("climate")
        assert "off" in options
        assert "heat" in options
        assert "cool" in options

    def test_returns_options_for_ventilation(self):
        """Опции для вентиляции"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        options = integration._get_state_options("ventilation")
        assert "off" in options
        assert "low" in options
        assert "high" in options

    def test_returns_default_for_unknown(self):
        """Опции по умолчанию для неизвестного типа"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)

        options = integration._get_state_options("unknown")
        assert options == ["unknown"]


class TestGetCreatedEntities:
    """Тесты получения списка созданных сущностей"""

    def test_returns_copy_of_entities(self):
        """Возврат копии словаря сущностей"""
        ha_adapter = MagicMock()
        event_bus = MagicMock()
        integration = DashboardIntegration(ha_adapter, event_bus)
        integration._created_entities = {"test": "sensor.test"}

        entities = integration.get_created_entities()

        assert entities == {"test": "sensor.test"}
        assert entities is not integration._created_entities  # Это копия


class TestRecreateAllEntities:
    """Тесты воссоздания всех сущностей"""

    @pytest.mark.asyncio
    async def test_logs_recreation_for_each_entity(self):
        """Логирование воссоздания для каждой сущности"""
        ha_adapter = AsyncMock()
        event_bus = MagicMock()

        integration = DashboardIntegration(ha_adapter, event_bus)
        integration._created_entities = {
            "light.kitchen": "sensor.fsm_light.kitchen",
            "climate.bedroom": "sensor.fsm_climate.bedroom",
        }

        # Просто проверяем что метод выполняется без ошибок
        await integration._recreate_all_entities()
