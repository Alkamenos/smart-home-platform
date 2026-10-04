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
    async def test_unavailable_device_status_after_timeout(self):
        """T060: Устройство переходит в unavailable после 60 сек без обновлений.

        Раньше тест создавал устройство с устаревшим `last_state_update` и
        заканчивался комментарием «здесь мы просто проверяем структуру» — то
        есть не утверждал ничего и был зелёным при любом состоянии кода.

        Механика установлена чтением кода (`DeviceService._reset_unavailable_timer`,
        строки 1172–1196): таймер **не** создаётся при регистрации устройства, а
        запускается при обработке входящего изменения состояния и через 60 секунд
        переводит устройство в `unavailable`. Поэтому тест обязан сначала
        вызвать `handle_state_change`, иначе таймера не существует и проверять
        нечего.

        Ожидание 60 секунд заменено перехватом `asyncio.sleep` в модуле сервиса:
        это проверяет ту же ветвь кода, но за миллисекунды.
        """
        from unittest.mock import patch

        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        service = DeviceService(
            event_bus=EventBus(),
            persistence_module=None,
            ha_adapter=None,
        )

        device = Device(
            ha_entity_id="sensor.temperature",
            source_id=UUID(int=0),
            name="Temperature Sensor",
            device_type="sensor",
            status="available",
        )
        service._devices[device.id] = device

        # Форма события та же, что у реального вызова `_on_ha_state_change_event`
        # (`device_service.py:125-133`): состояние лежит в `data.new_state`.
        # Плоский словарь приводит к тихому возврату по warning «Event data
        # missing entity_id» — таймер при этом не создаётся вовсе.
        state_change = {
            "data": {
                "entity_id": "sensor.temperature",
                "old_state": {"state": "off"},
                "new_state": {"state": "on", "attributes": {}},
            }
        }

        # Порог зашит в коде; перехватываем его, чтобы не ждать 60 секунд.
        observed_delays: list[float] = []
        real_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            observed_delays.append(delay)
            return await real_sleep(0, *args, **kwargs)

        with patch("services.device_service.asyncio.sleep", new=fast_sleep):
            await service.handle_state_change(state_change)
            # Дать созданной задаче выполниться
            for _ in range(5):
                await real_sleep(0)

        assert observed_delays == [60], f"ожидался порог 60 секунд, фактически {observed_delays}"

        resolved = await service.get_device(device.id)
        assert resolved is not None, "устройство обязано читаться после таймаута"
        assert resolved.status == "unavailable", (
            f"ожидался статус unavailable после 60 секунд без обновлений, получен {resolved.status}"
        )

    @pytest.mark.asyncio
    async def test_state_change_resets_unavailable_timer(self):
        """Новое обновление состояния отменяет отложенный перевод в unavailable.

        Парная проверка к предыдущей: без неё тест проходил бы и при сломанном
        сбросе таймера — устройство уходило бы в `unavailable` даже при
        регулярных обновлениях.
        """
        from core.events.event_bus import EventBus
        from core.models.device import Device
        from services.device_service import DeviceService

        service = DeviceService(
            event_bus=EventBus(),
            persistence_module=None,
            ha_adapter=None,
        )

        device = Device(
            ha_entity_id="sensor.frequent_updates",
            source_id=UUID(int=0),
            name="Датчик с частыми обновлениями",
            device_type="sensor",
            status="available",
        )
        service._devices[device.id] = device

        state_change = {
            "data": {
                "entity_id": "sensor.frequent_updates",
                "old_state": {"state": "off"},
                "new_state": {"state": "on", "attributes": {}},
            }
        }

        await service.handle_state_change(state_change)
        assert device.id in service._unavailable_timers, "таймер обязан появиться"
        first_task = service._unavailable_timers[device.id]

        await service.handle_state_change(state_change)
        second_task = service._unavailable_timers[device.id]

        assert second_task is not first_task, "новое обновление обязано завести новый таймер"

        # `Task.cancel()` лишь запрашивает отмену: флаг `cancelled()` становится
        # True только после того, как цикл событий доставит `CancelledError`.
        # Поэтому проверять флаг можно лишь уступив управление — иначе тест
        # утверждал бы промежуточное состояние и падал бы на корректном коде.
        await asyncio.sleep(0)
        assert first_task.cancelled(), "предыдущий таймер должен быть отменён при новом обновлении"
        assert (await service.get_device(device.id)).status == "available"

        # Отменённая задача не должна переводить устройство в unavailable
        await asyncio.sleep(0)
        assert (await service.get_device(device.id)).status == "available", (
            "отменённый таймер не должен переводить устройство в unavailable"
        )


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
