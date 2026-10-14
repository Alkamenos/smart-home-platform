"""
Интеграционные тесты для синхронизации состояния устройств и команд.

T046: Синхронизация состояния через WebSocket (<=5 сек)
T047: Отправка команд и обработка ошибок
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest


class TestStateSyncIntegration:
    """Интеграционные тесты для синхронизации состояния."""

    @pytest.mark.asyncio
    async def test_device_state_syncs_within_5_seconds(self):
        """T046: Состояние устройства синхронизируется за <= 5 секунд."""
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

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

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

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
        # Формат соответствует payload события HA (event.data), который ожидает
        # DeviceService.handle_state_change
        state_change_event = {
            "event_type": "state_changed",
            "data": {
                "entity_id": "light.living_room",
                "old_state": {"state": "off"},
                "new_state": {"state": "on", "brightness": 150},
            },
        }

        # Обрабатываем событие
        if hasattr(service, "handle_state_change"):
            await service.handle_state_change(state_change_event)

            # Проверяем что состояние обновилось
            updated = await service.get_device(device.id)
            assert updated.state.get("state") == "on"

    @pytest.mark.asyncio
    async def test_silence_is_not_unavailability(self):
        """Молчание прибора не делает его недоступным (B70).

        Раньше сервис заводил таймер: 60 секунд без обновлений — и прибор
        объявлялся `unavailable`. Но Home Assistant шлёт событие только при
        изменении: лампа, которая просто горит, молчит — и платформа объявляла её
        сломанной (боевой случай 2026-10-14: «Свет над столом: прибор
        недоступен» при включённой лампе). Теперь доступность берётся из
        состояния прибора, которое ставит сам Home Assistant.
        """
        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=None)
        device = Device(
            ha_entity_id="light.svet_nad_stolom",
            source_id=UUID(int=0),
            name="Свет над столом",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device
        service._index.add_device(device)

        await service.handle_state_change(
            {
                "data": {
                    "entity_id": "light.svet_nad_stolom",
                    "old_state": {"state": "off"},
                    "new_state": {"state": "on", "attributes": {}},
                }
            }
        )
        # Уступаем управление: если бы таймер остался, задача успела бы отметиться.
        for _ in range(5):
            await asyncio.sleep(0)

        resolved = await service.get_device(device.id)
        assert resolved.status == "available", (
            f"молчание принято за недоступность: {resolved.status}"
        )

    @pytest.mark.asyncio
    async def test_ha_reported_unavailable_marks_device_unavailable(self):
        """Home Assistant объявил прибор потерянным — платформа соглашается."""
        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=None)
        device = Device(
            ha_entity_id="light.vorota_sever",
            source_id=UUID(int=0),
            name="Ворота (север)",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device
        service._index.add_device(device)

        await service.handle_state_change(
            {
                "data": {
                    "entity_id": "light.vorota_sever",
                    "old_state": {"state": "on"},
                    "new_state": {"state": "unavailable", "attributes": {}},
                }
            }
        )

        assert (await service.get_device(device.id)).status == "unavailable"

    @pytest.mark.asyncio
    async def test_returning_device_becomes_available_again(self):
        """Прибор вернулся — доступность возвращается вместе с состоянием."""
        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        service = DeviceService(event_bus=EventBus(), persistence_module=None, ha_adapter=None)
        device = Device(
            ha_entity_id="light.kalitka_iug",
            source_id=UUID(int=0),
            name="Калитка (юг)",
            device_type="light",
            status="unavailable",
        )
        service._devices[device.id] = device
        service._index.add_device(device)

        await service.handle_state_change(
            {
                "data": {
                    "entity_id": "light.kalitka_iug",
                    "old_state": {"state": "unavailable"},
                    "new_state": {"state": "off", "attributes": {}},
                }
            }
        )

        assert (await service.get_device(device.id)).status == "available"


class TestCommandExecutionIntegration:
    """Интеграционные тесты для выполнения команд."""

    @pytest.mark.asyncio
    async def test_execute_command_sends_to_ha(self):
        """T047: Команда успешно отправляется в Home Assistant."""
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

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
        """T047: Ошибка внешней системы превращается в отказ с её причиной.

        Раньше тест подавлял `Exception` и не содержал ни одного утверждения, а
        весь тел был обёрнут в `if hasattr(...)`. То есть он проходил и когда
        ошибка не возникала вовсе, и когда возникала, и когда метода не было.
        Теперь утверждается конкретное поведение: `execute_command` гасит сбой
        адаптера и поднимает `RuntimeError` с текстом причины.
        """
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(side_effect=Exception("HA Service Error"))

        service = DeviceService(
            event_bus=EventBus(),
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

        with pytest.raises(RuntimeError, match="HA Service Error"):
            await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters={},
            )

    @pytest.mark.asyncio
    async def test_command_failure_is_recorded_in_history(self):
        """Провал команды остаётся в истории со статусом failed и причиной.

        Парная проверка к предыдущей: без неё тест проходил бы и при потере
        записи о неудачной команде — то есть при самом тихом виде отказа.
        """
        from uuid import UUID

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        mock_ha_adapter = AsyncMock()
        mock_ha_adapter.call_service = AsyncMock(side_effect=Exception("HA Service Error"))

        service = DeviceService(
            event_bus=EventBus(),
            persistence_module=None,
            ha_adapter=mock_ha_adapter,
        )

        device = Device(
            ha_entity_id="light.test_history",
            source_id=UUID(int=0),
            name="Test Light History",
            device_type="light",
            status="available",
        )
        service._devices[device.id] = device

        with pytest.raises(RuntimeError):
            await service.execute_command(
                device_id=device.id,
                command_name="turn_on",
                parameters={},
            )

        assert len(service._commands) == 1, "запись о команде обязана сохраниться"
        record = next(iter(service._commands.values()))
        assert record["status"] == "failed", f"ожидался статус failed: {record['status']}"
        assert "HA Service Error" in record["error"], f"причина не записана: {record['error']}"
        assert record["completed_at"] is not None, "время завершения обязано проставляться"
