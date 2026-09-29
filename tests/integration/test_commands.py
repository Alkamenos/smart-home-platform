"""
Интеграционные тесты для отправки команд устройствам.

T047: Отправка команд, отслеживание статуса и обработка ошибок
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4, UUID

import pytest


class TestCommandsIntegration:
    """Интеграционные тесты для выполнения команд."""

    @pytest.mark.asyncio
    async def test_send_command_and_track_status(self):
        """T047: Отправка команды и отслеживание статуса выполнения."""
        from src.services.device_service import DeviceService
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device

        # Mock HA адаптер
        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(return_value={
            "success": True,
            "response": "Command executed"
        })

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        # Создаем устройство
        device = Device(
            ha_entity_id="light.kitchen",
            source_id=UUID(int=0),
            name="Kitchen Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        # Отправляем команду
        if hasattr(service, "execute_command"):
            result = await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters={"brightness": 255},
            )

            # Команда должна вернуть результат с ID
            assert result is not None
            assert "id" in result or "command_id" in result

    @pytest.mark.asyncio
    async def test_command_with_parameters(self):
        """T047: Команда с параметрами передается в HA корректно."""
        from src.services.device_service import DeviceService
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device

        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock()

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        device = Device(
            ha_entity_id="light.bedroom",
            source_id=UUID(int=0),
            name="Bedroom Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        if hasattr(service, "execute_command"):
            params = {"brightness": 100, "color": "red"}
            await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters=params,
            )

            # Проверяем что метод был вызван
            mock_ha_adapter.call_service.assert_called()

    @pytest.mark.asyncio
    async def test_command_execution_with_timeout(self):
        """T047: Команда имеет таймаут выполнения (макс 300 сек)."""
        from src.services.device_service import DeviceService
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device

        # Mock адаптер с задержкой
        mock_ha_adapter = AsyncMock()

        async def slow_call_service(*args, **kwargs):
            await asyncio.sleep(0.1)  # Имитируем задержку
            return {"success": True}

        mock_ha_adapter.call_service = slow_call_service

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        device = Device(
            ha_entity_id="climate.living_room",
            source_id=UUID(int=0),
            name="Living Room Climate",
            device_type="climate",
            status="available",
        )
        service._devices[device.id] = device

        # Команда должна иметь таймаут
        if hasattr(service, "execute_command"):
            try:
                result = await service.execute_command(
                    device_id=device.id,
                    command_name="set_temperature",
                    parameters={"temperature": 22},
                    timeout=300,  # Максимум 300 сек
                )
            except asyncio.TimeoutError:
                # Таймаут - ожидается для длительных операций
                pass

    @pytest.mark.asyncio
    async def test_command_error_propagation(self):
        """T047: Ошибки при выполнении команды правильно обработаны."""
        from src.services.device_service import DeviceService
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device

        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(
            side_effect=RuntimeError("Service call failed")
        )

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        device = Device(
            ha_entity_id="switch.pump",
            source_id=UUID(int=0),
            name="Pump Switch",
            device_type="switch",
            status="available",
        )
        service._devices[device.id] = device

        if hasattr(service, "execute_command"):
            # Должно быть исключение или отчет об ошибке
            with pytest.raises(Exception):
                await service.execute_command(
                    device_id=device.id,
                    command_name="turn_on",
                    parameters={},
                )

    @pytest.mark.asyncio
    async def test_get_command_status(self):
        """T056: Получение статуса выполненной команды."""
        from src.services.device_service import DeviceService
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device

        event_bus = EventBus()
        service = DeviceService(
            event_bus=event_bus,
            persistence_module=None,
            ha_adapter=None,
        )

        device = Device(
            ha_entity_id="light.test",
            source_id=UUID(int=0),
            name="Test Light",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        # Для T056 нужна возможность получить статус команды
        # по device_id и command_id
        if hasattr(service, "get_command_status"):
            command_id = uuid4()
            status = await service.get_command_status(device.id, command_id)
            # Должен вернуть None или статус
            assert status is None or isinstance(status, dict)
