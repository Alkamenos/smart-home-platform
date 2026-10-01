"""Тесты служебных путей DeviceService (spec 006, T044 — покрытие критического модуля).

Эти пути существовали до spec 006 и не относились к жизненному циклу
устройств: отзыв доступа, таймеры недоступности, метрики доступности и
вызов сервисов Home Assistant. Здесь они закрыты тестами, чтобы модуль
не оставался с непроверенными ветками.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from src.core.models.device import Device
from src.core.models.device_access import DeviceAccess
from src.services.device_service import DeviceService


@pytest.fixture
def persistence() -> MagicMock:
    """Заглушка постоянного хранилища.

    Returns:
        Объект с асинхронными методами хранилища.
    """
    store = MagicMock()
    store.devices = MagicMock()
    store.devices.save_device = AsyncMock()
    store.devices.save_devices = AsyncMock()
    store.devices.delete_device = AsyncMock(return_value=True)
    store.devices.load_devices_by_source = AsyncMock(return_value=[])
    store.devices.save_device_config = AsyncMock()
    store.devices.load_device_config = AsyncMock(return_value=None)
    store.device_access = MagicMock()
    store.device_access.load_access = AsyncMock(return_value=None)
    store.device_access.delete_access = AsyncMock(return_value=True)
    store.device_access.load_accesses_for_device = AsyncMock(return_value=[])
    store.device_access.load_accesses_for_user = AsyncMock(return_value=[])
    store.device_access.load_access_for_user_device = AsyncMock(return_value=None)
    store.device_access.save_access = AsyncMock()
    store.device_access.save_accesses = AsyncMock()
    store.device_access.delete_accesses_for_device = AsyncMock(return_value=0)
    store.save_device = AsyncMock()
    store.load_device_config = AsyncMock(return_value=None)
    store.save_device_config = AsyncMock()
    store.sources = MagicMock()
    store.sources.load_source = AsyncMock(return_value=None)
    store.sources.save_source = AsyncMock()
    return store


@pytest.fixture
def service(persistence: MagicMock) -> DeviceService:
    """Сервис устройств на заглушке хранилища.

    Args:
        persistence: Заглушка хранилища.

    Returns:
        Экземпляр сервиса.
    """
    return DeviceService(event_bus=MagicMock(), persistence_module=persistence)


def _device(entity_id: str = "light.helper") -> Device:
    """Создаёт устройство.

    Args:
        entity_id: Идентификатор сущности.

    Returns:
        Модель устройства.
    """
    return Device(
        ha_entity_id=entity_id,
        source_id=uuid4(),
        name=entity_id,
        device_type=entity_id.split(".")[0],
        status="available",
    )


class TestAccessHelpers:
    """Отзыв и чтение доступа."""

    @pytest.mark.asyncio
    async def test_revoke_access_should_publish_event(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Успешный отзыв публикует событие и возвращает True."""
        device = _device()
        access = DeviceAccess(
            device_id=device.id,
            user_id="viewer_user",
            role="viewer",
            granted_by="admin_user",
        )
        persistence.device_access.load_access = AsyncMock(return_value=access)
        service.event_bus.publish = AsyncMock()

        result = await service.revoke_access(access.id)

        assert result is True
        assert service.event_bus.publish.await_count == 1
        assert service.event_bus.publish.await_args_list[0].args[0] == "device.access_changed"

    @pytest.mark.asyncio
    async def test_revoke_access_should_swallow_storage_error(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Ошибка хранилища при отзыве не поднимается наружу."""
        persistence.device_access.delete_access = AsyncMock(side_effect=RuntimeError("disk"))

        assert await service.revoke_access(uuid4()) is False

    @pytest.mark.asyncio
    async def test_access_helpers_should_return_empty_without_store(self) -> None:
        """Без хранилища операции доступа возвращают пустые значения."""
        service = DeviceService(event_bus=MagicMock())

        assert await service.get_device_accesses(uuid4()) == []
        assert await service.get_user_accessible_devices("nobody") == []
        assert await service.revoke_access(uuid4()) is False

    @pytest.mark.asyncio
    async def test_access_helpers_should_survive_store_errors(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Ошибки хранилища в чтении доступа не поднимаются."""
        persistence.device_access.load_accesses_for_device = AsyncMock(
            side_effect=RuntimeError("disk")
        )

        assert await service.get_device_accesses(uuid4()) == []


class TestAvailabilityTimers:
    """Таймеры отслеживания недоступности устройства."""

    @pytest.mark.asyncio
    async def test_timer_should_be_created_and_replaced(self, service: DeviceService) -> None:
        """Для устройства создаётся таймер; повторный вызов заменяет его (T060)."""
        device = _device("light.silent")
        await service.add_device(device)

        service._reset_unavailable_timer(device.id)  # noqa: SLF001 — внутренний таймер
        first = service._unavailable_timers[device.id]  # noqa: SLF001

        service._reset_unavailable_timer(device.id)  # noqa: SLF001
        second = service._unavailable_timers[device.id]  # noqa: SLF001

        assert first is not second, "Старый таймер должен заменяться"
        await asyncio.sleep(0)
        assert first.cancelled(), "Задача старого таймера должна быть отменена"

        service._cancel_unavailable_timer(device.id)  # noqa: SLF001
        assert device.id not in service._unavailable_timers  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_timer_should_not_mark_available_device_again(
        self, service: DeviceService
    ) -> None:
        """Устройство, получившее обновление, недоступным не помечается."""
        device = _device("light.noisy")
        await service.add_device(device)

        service._reset_unavailable_timer(device.id)  # noqa: SLF001
        service._cancel_unavailable_timer(device.id)  # noqa: SLF001

        assert device.id not in service._unavailable_timers  # noqa: SLF001

    @pytest.mark.asyncio
    async def test_cancel_timer_should_tolerate_missing_timer(self, service: DeviceService) -> None:
        """Отмена несуществующего таймера безопасна."""
        service._cancel_unavailable_timer(uuid4())  # noqa: SLF001


class TestAvailabilityMetrics:
    """Метрики доступности устройств."""

    @pytest.mark.asyncio
    async def test_metrics_should_aggregate_by_source_and_type(
        self, service: DeviceService
    ) -> None:
        """Метрики считают доступные и недоступные устройства по источникам."""
        service._metrics = MagicMock()  # noqa: SLF001
        source_id = uuid4()
        await service.add_device(_device("light.up"))
        await service.add_device(_device("light.down"))
        broken = _device("light.broken")
        broken.status = "unavailable"
        broken.source_id = source_id
        service._devices[broken.id] = broken  # noqa: SLF001

        service._update_device_availability_metrics()  # noqa: SLF001

        service._metrics.set_devices_available.assert_called()
        service._metrics.set_devices_unavailable.assert_called()

    @pytest.mark.asyncio
    async def test_metrics_failure_should_not_escape(self, service: DeviceService) -> None:
        """Ошибка метрик не прерывает работу сервиса."""
        service._metrics = MagicMock()  # noqa: SLF001
        service._metrics.set_devices_available.side_effect = RuntimeError("registry")
        await service.add_device(_device("light.metrics"))

        service._update_device_availability_metrics()  # noqa: SLF001
        service.update_sources_connected_count(2)

    def test_cache_and_index_helpers_should_report_stats(self, service: DeviceService) -> None:
        """Служебные методы кэша и индекса отвечают без ошибок."""
        assert isinstance(service.get_cache_stats(), dict)
        assert isinstance(service.get_index_stats(), dict)
        assert service.find_device_by_ha_entity_id("light.nothing") is None

    @pytest.mark.asyncio
    async def test_devices_by_source_should_return_empty_without_matches(
        self, service: DeviceService
    ) -> None:
        """Для источника без устройств возвращается пустой список."""
        assert await service.get_devices_by_source(uuid4()) == []


class TestConfigAndCacheInvalidation:
    """Обновление конфигурации и сброс кэша."""

    @pytest.mark.asyncio
    async def test_update_config_should_persist_and_publish(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Обновление конфигурации сохраняет её и публикует событие."""
        device = _device("light.config")
        await service.add_device(device)
        service.event_bus.publish = AsyncMock()
        persistence.save_device = AsyncMock()

        config = await service.update_device_config(device.id, display_name="Лампа")

        assert config.display_name == "Лампа"
        assert service.event_bus.publish.await_count == 1
        assert persistence.save_device.await_count >= 1

    @pytest.mark.asyncio
    async def test_update_config_should_surface_storage_error(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Ошибка хранилища при обновлении конфигурации поднимается."""
        device = _device("light.config_fail")
        await service.add_device(device)
        persistence.save_device = AsyncMock(side_effect=RuntimeError("disk"))

        with pytest.raises(Exception):  # noqa: B017 — любая ошибка хранилища допустима
            await service.update_device_config(device.id, display_name="Лампа")

    def test_invalidate_cache_should_drop_device_and_source(self, service: DeviceService) -> None:
        """Сброс кэша вытесняет устройство и его источник."""
        device = _device("light.cache")
        service._devices[device.id] = device  # noqa: SLF001

        service.invalidate_device_cache(device.id)  # noqa: SLF001
        source_invalidated = service.invalidate_source_cache(device.source_id)  # noqa: SLF001

        assert source_invalidated >= 0

    @pytest.mark.asyncio
    async def test_state_change_should_update_device_state(
        self, service: DeviceService, persistence: MagicMock
    ) -> None:
        """Событие состояния обновляет устройство и публикует изменение."""
        device = _device("light.stated")
        await service.add_device(device)
        service.event_bus.publish = AsyncMock()

        await service.handle_state_change(
            {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "light.stated",
                    "new_state": {"state": "off", "attributes": {"friendly_name": "Stated"}},
                    "old_state": {"state": "on", "attributes": {}},
                },
            }
        )

        stored = await service.get_device(device.id)
        assert stored is not None
        assert (stored.state or {}).get("state") == "off"
        assert service.event_bus.publish.await_count >= 1

    @pytest.mark.asyncio
    async def test_state_change_for_unknown_device_should_not_fail(
        self, service: DeviceService
    ) -> None:
        """Событие неизвестного устройства не поднимает исключений."""
        await service.handle_state_change(
            {
                "event_type": "state_changed",
                "data": {
                    "entity_id": "light.unknown",
                    "new_state": {"state": "on", "attributes": {}},
                    "old_state": {"state": "off", "attributes": {}},
                },
            }
        )

    @pytest.mark.asyncio
    async def test_command_status_should_be_available(self, service: DeviceService) -> None:
        """Статус команды читается и для неизвестной команды возвращает None."""
        assert await service.get_command_status(uuid4(), uuid4()) is None


class TestIndexAndMetricsHelpers:
    """Перестроение индекса и прокси-метрики."""

    def test_index_helpers_should_rebuild_and_query(self, service: DeviceService) -> None:
        """Индекс перестраивается из памяти и отвечает на запросы."""
        service.add_devices_to_cache_and_index([_device("light.a"), _device("switch.b")])  # noqa: SLF001

        service.rebuild_index()

        assert len(service.find_devices_by_type("light")) == 1
        assert service.get_index_stats()["total_devices"] == 2

    def test_metrics_proxies_should_reach_collector(self, service: DeviceService) -> None:
        """Прокси-метрики доходят до сборщика и не падают при его ошибках."""
        service._metrics = MagicMock()  # noqa: SLF001

        service.update_cache_metrics(1024)
        service.record_cache_hit("device")
        service.record_cache_miss("device")
        service.update_sources_connected_count(1)

        assert service._metrics.set_cache_size.called  # noqa: SLF001
        assert service._metrics.record_cache_hit.called  # noqa: SLF001
        assert service._metrics.record_cache_miss.called  # noqa: SLF001

        service._metrics.set_cache_size.side_effect = RuntimeError("registry")  # noqa: SLF001
        service.update_cache_metrics(2048)
        service.record_cache_hit()
