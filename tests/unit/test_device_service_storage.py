"""Тесты операций сервиса устройств: список, гидратация, добавление, удаление.

Покрывают FR-001…FR-003 (единый источник устройств) и FR-004 (переживание
перезапуска) из спецификации specs/006.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from src.core.events.event_bus import EventBus
from src.core.models.device import Device
from src.services.device_service import DeviceService

from tests.helpers.device_factory import make_device, make_persistence, seed_persistence


@pytest.fixture
def real_persistence(tmp_path: Path):
    """Менеджер хранения в изолированном временном каталоге.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Экземпляр PersistenceManager.
    """
    return make_persistence(tmp_path / "data")


@pytest.fixture
def mock_persistence() -> MagicMock:
    """Мок менеджера хранения.

    Returns:
        Мок PersistenceManager с асинхронными методами.
    """
    persistence = MagicMock()
    persistence.devices = MagicMock(
        save_device=AsyncMock(),
        save_devices=AsyncMock(),
        load_device=AsyncMock(return_value=None),
        load_all_devices=AsyncMock(return_value=[]),
        delete_device=AsyncMock(return_value=True),
    )
    persistence.sources = MagicMock()
    persistence.device_access = MagicMock(delete_accesses_for_device=AsyncMock(return_value=0))
    return persistence


@pytest.fixture
def service(mock_persistence: MagicMock) -> DeviceService:
    """Сервис устройств с мокнутым хранилищем и адаптером.

    Args:
        mock_persistence: Мок хранилища.

    Returns:
        Экземпляр DeviceService.
    """
    return DeviceService(
        event_bus=EventBus(),
        persistence_module=mock_persistence,
        ha_adapter=AsyncMock(),
    )


class TestDeviceServiceListing:
    """Тесты чтения списка устройств (FR-003)."""

    async def test_get_all_devices_should_return_empty_list_when_no_devices(
        self, service: DeviceService
    ) -> None:
        """Без устройств возвращается пустой список."""
        assert await service.get_all_devices() == []

    async def test_get_all_devices_should_return_devices_added_via_primitives(
        self, service: DeviceService, mock_persistence: MagicMock
    ) -> None:
        """Добавленные устройства видны в списке."""
        device = make_device(ha_entity_id="light.kitchen")

        await service.add_device(device)

        devices = await service.get_all_devices()
        assert [d.ha_entity_id for d in devices] == ["light.kitchen"]

    async def test_list_devices_should_filter_by_source(self, service: DeviceService) -> None:
        """Список фильтруется по источнику."""
        source_a, source_b = uuid4(), uuid4()
        await service.add_device(make_device(ha_entity_id="light.a", source_id=source_a))
        await service.add_device(make_device(ha_entity_id="light.b", source_id=source_b))

        devices = await service.list_devices(source_id=source_a)

        assert [d.ha_entity_id for d in devices] == ["light.a"]


class TestDeviceServiceHydration:
    """Тесты гидратации при старте (FR-004, D-002)."""

    async def test_hydrate_should_load_devices_from_persistence(self, real_persistence) -> None:
        """После гидратации устройства из хранилища доступны через get_device."""
        device = make_device(ha_entity_id="light.kitchen")
        await seed_persistence(real_persistence, [device])

        service = DeviceService(
            event_bus=EventBus(),
            persistence_module=real_persistence,
            ha_adapter=AsyncMock(),
        )
        loaded = await service.hydrate_from_persistence()

        assert loaded == 1
        fetched = await service.get_device(device.id)
        assert fetched is not None
        assert fetched.ha_entity_id == "light.kitchen"

    async def test_hydrate_should_survive_absent_persistence(self, service: DeviceService) -> None:
        """Без хранилища гидратация не падает и возвращает 0."""
        service_without_storage = DeviceService(
            event_bus=EventBus(),
            persistence_module=None,
            ha_adapter=AsyncMock(),
        )

        assert await service_without_storage.hydrate_from_persistence() == 0


class TestDeviceServiceAddDevice:
    """Тесты добавления устройства (FR-001, FR-004)."""

    async def test_add_device_should_persist_device(
        self, service: DeviceService, mock_persistence: MagicMock
    ) -> None:
        """Добавление сохраняет устройство в постоянное хранилище."""
        device = make_device(ha_entity_id="light.kitchen")

        await service.add_device(device)

        mock_persistence.devices.save_device.assert_awaited_once()
        assert mock_persistence.devices.save_device.await_args.args[0].id == device.id

    async def test_add_device_should_be_visible_via_get_device(
        self, service: DeviceService
    ) -> None:
        """Добавленное устройство читается через get_device."""
        device = make_device(ha_entity_id="light.kitchen")

        await service.add_device(device)

        assert (await service.get_device(device.id)) is not None

    async def test_add_device_should_index_device_by_type(self, service: DeviceService) -> None:
        """Добавленное устройство попадает в индекс по типу."""
        device = make_device(ha_entity_id="light.kitchen", device_type="light")

        await service.add_device(device)

        found = service.find_devices_by_type("light")
        assert [d.id for d in found] == [device.id]

    async def test_add_device_should_update_existing_device_when_entity_repeats(
        self, service: DeviceService, mock_persistence: MagicMock
    ) -> None:
        """Повторное добавление того же идентификатора обновляет, а не плодит (FR-008)."""
        source_id = uuid4()
        first = make_device(ha_entity_id="light.kitchen", source_id=source_id, name="Свет")
        await service.add_device(first)

        second = make_device(ha_entity_id="light.kitchen", source_id=source_id, name="Свет новый")
        await service.add_device(second)

        devices = await service.get_all_devices()
        assert len(devices) == 1
        assert devices[0].name == "Свет новый"


class TestDeviceServiceRemoveDevice:
    """Тесты удаления устройства (FR-025 подготовка)."""

    async def test_remove_device_should_delete_from_persistence_and_index(
        self, service: DeviceService, mock_persistence: MagicMock
    ) -> None:
        """Удаление чистит хранилище, кэш и индексы."""
        device = make_device(ha_entity_id="light.kitchen")
        await service.add_device(device)

        removed = await service.remove_device(device.id)

        assert removed is True
        mock_persistence.devices.delete_device.assert_awaited_once_with(device.id)
        assert await service.get_device(device.id) is None
        assert service.find_devices_by_type("light") == []

    async def test_remove_device_should_be_idempotent(self, service: DeviceService) -> None:
        """Повторное удаление возвращает False и не поднимает исключение."""
        device = make_device(ha_entity_id="light.kitchen")
        await service.add_device(device)
        await service.remove_device(device.id)

        assert await service.remove_device(device.id) is False


class TestDeviceServiceIntegrationWithRealPersistence:
    """Тесты сквозного пути «постоянное хранилище + сервис»."""

    async def test_device_should_survive_service_restart(self, tmp_path: Path) -> None:
        """Устройство, добавленное одним сервисом, видно сервису после «перезапуска» (FR-004)."""
        persistence = make_persistence(tmp_path / "data")
        first_service = DeviceService(
            event_bus=EventBus(),
            persistence_module=persistence,
            ha_adapter=AsyncMock(),
        )
        device = make_device(ha_entity_id="light.kitchen")
        await first_service.add_device(device)

        second_service = DeviceService(
            event_bus=EventBus(),
            persistence_module=make_persistence(tmp_path / "data"),
            ha_adapter=AsyncMock(),
        )
        await second_service.hydrate_from_persistence()

        assert [d.ha_entity_id for d in await second_service.get_all_devices()] == ["light.kitchen"]

    async def test_removed_device_should_not_come_back_after_hydration(
        self, tmp_path: Path
    ) -> None:
        """Удалённое устройство не возвращается после гидратации (FR-025)."""
        data_dir = tmp_path / "data"
        service = DeviceService(
            event_bus=EventBus(),
            persistence_module=make_persistence(data_dir),
            ha_adapter=AsyncMock(),
        )
        device: Device = make_device(ha_entity_id="light.kitchen")
        await service.add_device(device)
        await service.remove_device(device.id)

        restarted = DeviceService(
            event_bus=EventBus(),
            persistence_module=make_persistence(data_dir),
            ha_adapter=AsyncMock(),
        )
        await restarted.hydrate_from_persistence()

        assert await restarted.get_all_devices() == []
