"""
Интеграционные тесты для отправки команд устройствам.

T047: Отправка команд, отслеживание статуса и обработка ошибок
"""

import asyncio
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest


class TestCommandsIntegration:
    """Интеграционные тесты для выполнения команд."""

    @pytest.mark.asyncio
    async def test_send_command_and_track_status(self):
        """T047: Отправка команды и отслеживание статуса выполнения."""
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        # Mock HA адаптер
        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(
            return_value={"success": True, "response": "Command executed"}
        )

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
            # execute_command возвращает pydantic-модель, а не dict:
            # в pydantic v2 проверка `'id' in model` не работает — нужен model_dump()
            data = result.model_dump() if hasattr(result, "model_dump") else result
            assert "id" in data or "command_id" in data

    @pytest.mark.asyncio
    async def test_command_with_parameters(self):
        """T047: Команда с параметрами передается в HA корректно."""
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

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
        """T047: Команда укладывается в заданный таймаут и даёт результат.

        Раньше тест подавлял `TimeoutError` и не утверждал ничего: при задержке
        0.1 с и таймауте 300 с таймаут не мог наступить, поэтому тест был зелёным
        независимо от того, выполнилась команда или нет. Теперь утверждается
        результат, а превышение таймаута проверяется отдельным тестом ниже.
        """
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

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

        result = await service.execute_command(
            device_id=device.id,
            command_name="set_temperature",
            parameters={"temperature": 22},
            timeout=300,  # Максимум 300 сек
        )

        assert result.status == "success", f"ожидался успех, получен {result.status}"
        assert result.result == {"success": True}, "результат команды не передан"
        assert result.device_id == device.id
        assert result.command_name == "set_temperature"
        assert result.completed_at is not None, "время завершения обязано проставляться"

    @pytest.mark.asyncio
    async def test_command_timeout_is_reported_not_swallowed(self):
        """SC-012: превышение времени выполнения отражается в результате.

        Задержка адаптера заведомо больше таймаута, поэтому исход предсказуем:
        команда обязана провалиться с сообщением, называющим таймаут. Раньше
        это поведение не проверялось нигде — таймаут «проверялся» подавлением
        исключения, то есть не проверялся вовсе.
        """
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()

        async def too_slow_call_service(*args, **kwargs):
            await asyncio.sleep(5)
            return {"success": True}

        mock_ha_adapter.call_service = too_slow_call_service

        service = DeviceService(
            event_bus=EventBus(),
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

        with pytest.raises(RuntimeError, match="Command timeout after 1 seconds"):
            await service.execute_command(
                device_id=device.id,
                command_name="set_temperature",
                parameters={"temperature": 22},
                timeout=1,
            )

    @pytest.mark.asyncio
    async def test_command_timeout_is_capped_at_300_seconds(self):
        """Таймаут ограничен 300 секундами даже если задан больший.

        Проверяется перехватом `asyncio.wait_for`, потому что иначе единственным
        способом убедиться в ограничении было бы ждать 300 секунд. Утверждение
        делается на фактическом значении, переданном в ожидание, а не на
        косвенном признаке.
        """
        from unittest.mock import patch

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()

        async def immediate_call_service(*args, **kwargs):
            return {"success": True}

        mock_ha_adapter.call_service = immediate_call_service

        service = DeviceService(
            event_bus=EventBus(),
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

        real_wait_for = asyncio.wait_for
        observed: list[float] = []

        async def recording_wait_for(awaitable, timeout):
            observed.append(timeout)
            return await real_wait_for(awaitable, timeout)

        with patch("src.services.device_service.asyncio.wait_for", new=recording_wait_for):
            await service.execute_command(
                device_id=device.id,
                command_name="set_temperature",
                parameters={"temperature": 22},
                timeout=10_000,
            )

        assert observed == [300], f"ожидался таймаут 300, фактически {observed}"

    @pytest.mark.asyncio
    async def test_command_timeout_within_limit_is_not_capped(self):
        """Таймаут меньше 300 секунд передаётся без изменений."""
        from unittest.mock import patch

        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()

        async def immediate_call_service(*args, **kwargs):
            return {"success": True}

        mock_ha_adapter.call_service = immediate_call_service

        service = DeviceService(
            event_bus=EventBus(),
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

        real_wait_for = asyncio.wait_for
        observed: list[float] = []

        async def recording_wait_for(awaitable, timeout):
            observed.append(timeout)
            return await real_wait_for(awaitable, timeout)

        with patch("src.services.device_service.asyncio.wait_for", new=recording_wait_for):
            await service.execute_command(
                device_id=device.id,
                command_name="set_temperature",
                parameters={"temperature": 22},
                timeout=42,
            )

        assert observed == [42], f"ожидался таймаут 42, фактически {observed}"

    @pytest.mark.asyncio
    async def test_command_error_propagation(self):
        """T047: Ошибки при выполнении команды правильно обработаны."""
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(side_effect=RuntimeError("Service call failed"))

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
            with pytest.raises(RuntimeError):
                await service.execute_command(
                    device_id=device.id,
                    command_name="turn_on",
                    parameters={},
                )

    @pytest.mark.asyncio
    async def test_get_command_status(self):
        """T056: Получение статуса выполненной команды."""
        from src.core.events.event_bus import EventBus
        from src.core.models.device import Device
        from src.services.device_service import DeviceService

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
