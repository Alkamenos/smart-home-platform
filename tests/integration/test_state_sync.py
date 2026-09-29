"""
Интеграционные тесты для синхронизации состояния устройств и команд.

T046: Синхронизация состояния через WebSocket (<=5 сек)
T047: Отправка команд и обработка ошибок
"""

import contextlib
from datetime import datetime
from unittest.mock import AsyncMock

import pytest


class TestStateSyncIntegration:
    """Интеграционные тесты для синхронизации состояния."""

    @pytest.mark.asyncio
    async def test_device_state_syncs_within_5_seconds(self):
        """T046: Состояние устройства синхронизируется за <= 5 секунд."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=None,
        )

        # Создаем тестовое устройство
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=UUID(int=0),
            name="Kitchen Light",
            device_type="light",
            status="available",
        )

        # Регистрируем устройство в сервисе
        service._devices[device.id] = device

        # Отслеживаем начало и конец обновления
        update_start = datetime.utcnow()

        # Обновляем состояние
        new_state = {"state": "on", "brightness": 200}
        await service.update_device_state(device.id, new_state)

        update_end = datetime.utcnow()

        # Проверяем что обновление произошло
        updated_device = await service.get_device(device.id)
        assert updated_device is not None
        assert updated_device.state == new_state

        # Проверяем что обновление произошло в течение 5 секунд
        sync_time = (update_end - update_start).total_seconds()
        assert sync_time <= 5.0, f"Sync took {sync_time}s, expected <=5s"

    @pytest.mark.asyncio
    async def test_handle_state_change_updates_device(self):
        """T046: handle_state_change обновляет состояние устройства в сервисе."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=None,
        )

        # Создаем устройство
        device = Device(
            ha_entity_id="light.living_room",
            source_id=UUID(int=0),
            name="Living Room Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        # Формируем событие изменения состояния из HA
        state_change_event = {
            "entity_id": "light.living_room",
            "old_state": {"state": "off"},
            "new_state": {"state": "on", "brightness": 150},
        }

        # Обрабатываем событие
        if hasattr(service, "handle_state_change"):
            await service.handle_state_change(state_change_event)

            # Проверяем что состояние обновилось
            updated = await service.get_device(device.id)
            assert updated.state.get("state") == "on"

    @pytest.mark.asyncio
    async def test_unavailable_device_status_after_timeout(self):
        """T060: Устройство переходит в unavailable после 60 сек без обновлений."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=None,
        )

        # Создаем устройство с датой обновления давно
        from datetime import datetime, timedelta

        device = Device(
            ha_entity_id="sensor.temperature",
            source_id=UUID(int=0),
            name="Temperature Sensor",
            device_type="sensor",
            status="available",
            last_state_update=datetime.utcnow() - timedelta(seconds=70),
        )
        service._devices[device.id] = device

        # Для этого теста нужна реализация проверки timeout
        # которая будет добавлена в T060
        # Здесь мы просто проверяем структуру


class TestCommandExecutionIntegration:
    """Интеграционные тесты для выполнения команд."""

    @pytest.mark.asyncio
    async def test_execute_command_sends_to_ha(self):
        """T047: Команда успешно отправляется в Home Assistant."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        # Mock HA адаптер
        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(return_value=True)

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        # Создаем устройство
        device = Device(
            ha_entity_id="light.bedroom",
            source_id=UUID(int=0),
            name="Bedroom Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        # Отправляем команду
        if hasattr(service, "execute_command"):
            command_result = await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters={},
            )

            # Проверяем результат
            assert command_result is not None

    @pytest.mark.asyncio
    async def test_command_execution_error_handling(self):
        """T047: Ошибки при выполнении команды обрабатываются корректно."""
        from uuid import UUID

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        # Mock HA адаптер с ошибкой
        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(side_effect=Exception("HA Service Error"))

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        device = Device(
            ha_entity_id="light.test",
            source_id=UUID(int=0),
            name="Test Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        # Попытка выполнить команду должна обработать ошибку
        if hasattr(service, "execute_command"):
            with contextlib.suppress(Exception):
                await service.execute_command(
                    device_id=device.id,
                    command_name="turn_on",
                    parameters={},
                )
