"""Тесты путей сбоя синхронизации и сканирования источника (spec 006, T044).

Слияние результатов синхронизации с единым хранилищем не должно падать
из-за недоступного хранилища, отказа в выдаче прав или неработающего
движка машин состояний: устройства, которые уже загружены, обязаны уцелеть
(FR-017).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from src.core.discovery.discovery_service import DeviceDiscoveryService
from src.core.models.device import Device
from src.core.models.ha_source import HASource
from src.services.device_service import DeviceService


def _device(entity_id: str = "light.sync_a", source_id: UUID | None = None) -> Device:
    """Создаёт устройство для проверок слияния.

    Args:
        entity_id: Идентификатор сущности.
        source_id: Идентификатор источника.

    Returns:
        Модель устройства.
    """
    return Device(
        ha_entity_id=entity_id,
        source_id=source_id or uuid4(),
        name=entity_id,
        device_type=entity_id.split(".")[0],
        status="available",
    )


def _service_with_source(source_id: UUID, source: HASource | None = None) -> DeviceService:
    """Создаёт сервис с источником в заглушке хранилища.

    Args:
        source_id: Идентификатор источника.
        source: Источник для заглушки (создаётся по умолчанию).

    Returns:
        Экземпляр сервиса.
    """
    persistence = MagicMock()
    persistence.sources = MagicMock()
    persistence.sources.load_source = AsyncMock(
        return_value=source
        or HASource(
            id=source_id,
            name="HA",
            url="http://ha.local:8123",
            token="sync_token_1",
        )
    )
    persistence.sources.save_source = AsyncMock()
    persistence.devices = MagicMock()
    persistence.devices.save_devices = AsyncMock()
    persistence.devices.save_device = AsyncMock()
    persistence.devices.load_devices_by_source = AsyncMock(return_value=[])
    persistence.devices.delete_device = AsyncMock(return_value=True)
    persistence.device_access = MagicMock()
    persistence.device_access.delete_accesses_for_device = AsyncMock(return_value=1)
    persistence.device_access.save_access = AsyncMock()

    return DeviceService(
        event_bus=MagicMock(), persistence_module=persistence, ha_adapter=AsyncMock()
    )


def _patch_ha(states: list[dict], connected: bool = True) -> object:
    """Подменяет REST-клиент Home Assistant.

    Args:
        states: Состояния источника.
        connected: Результат подключения.

    Returns:
        Контекст-менеджер подмены.
    """

    async def _connect(*args: object, **kwargs: object) -> bool:
        return connected

    async def _devices(*args: object, **kwargs: object) -> list[dict]:
        return states

    async def _areas(*args: object, **kwargs: object) -> list[dict]:
        return []

    with (
        patch("src.adapters.home_assistant.rest_client.HARestClient.connect_to_ha", new=_connect),
        patch("src.adapters.home_assistant.rest_client.HARestClient.fetch_devices", new=_devices),
        patch("src.adapters.home_assistant.rest_client.HARestClient.fetch_areas", new=_areas),
    ):
        yield


class TestSyncFailurePaths:
    """Сбои на пути синхронизации не теряют уже загруженные устройства."""

    @pytest.mark.asyncio
    async def test_storage_failure_should_keep_devices(self) -> None:
        """Ошибка чтения хранилища не прерывает синхронизацию."""
        source_id = uuid4()
        service = _service_with_source(source_id)
        service.persistence.devices.load_devices_by_source = AsyncMock(
            side_effect=RuntimeError("storage unavailable")
        )

        with patch("src.adapters.home_assistant.rest_client.HARestClient") as client_class:
            client = AsyncMock()
            client.connect_to_ha = AsyncMock(return_value=True)
            client.fetch_devices = AsyncMock(
                return_value=[{"entity_id": "light.sync_a", "state": "on", "attributes": {}}]
            )
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client_class.return_value = client

            result = await service.sync_devices_from_source(source_id)

        assert [device.ha_entity_id for device in result] == ["light.sync_a"]

    @pytest.mark.asyncio
    async def test_access_grant_failure_should_not_break_sync(self) -> None:
        """Отказ в выдаче прав не мешает сохранить устройство."""
        source_id = uuid4()
        service = _service_with_source(source_id)
        service.grant_access = AsyncMock(side_effect=RuntimeError("denied"))

        with patch("src.adapters.home_assistant.rest_client.HARestClient") as client_class:
            client = AsyncMock()
            client.connect_to_ha = AsyncMock(return_value=True)
            client.fetch_devices = AsyncMock(
                return_value=[{"entity_id": "light.sync_b", "state": "on", "attributes": {}}]
            )
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client_class.return_value = client

            result = await service.sync_devices_from_source(source_id)

        assert [device.ha_entity_id for device in result] == ["light.sync_b"]

    @pytest.mark.asyncio
    async def test_sync_without_persistence_should_fail(self) -> None:
        """Без постоянного хранилища синхронизация невозможна."""
        service = DeviceService(event_bus=MagicMock(), persistence_module=None)

        with pytest.raises(ValueError):
            await service.sync_devices_from_source(uuid4())

    @pytest.mark.asyncio
    async def test_removed_devices_without_engine_should_stay_marked(self) -> None:
        """Без движка машин состояний устройство всё равно помечается."""
        source_id = uuid4()
        service = _service_with_source(source_id)
        known = _device("light.gone", source_id)
        service.persistence.devices.load_devices_by_source = AsyncMock(return_value=[known])
        await service.add_device(known)

        with patch("src.adapters.home_assistant.rest_client.HARestClient") as client_class:
            client = AsyncMock()
            client.connect_to_ha = AsyncMock(return_value=True)
            client.fetch_devices = AsyncMock(return_value=[])
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client_class.return_value = client

            await service.sync_devices_from_source(source_id)

        devices = await service.get_all_devices()
        assert devices[0].status == "removed_from_ha"

    @pytest.mark.asyncio
    async def test_engine_failure_should_not_abort_removal(self) -> None:
        """Ошибка движка при снятии автоматики не откатывает синхронизацию."""
        source_id = uuid4()
        service = _service_with_source(source_id)
        known = _device("light.gone_two", source_id)
        service.persistence.devices.load_devices_by_source = AsyncMock(return_value=[known])
        await service.add_device(known)

        broken_engine = MagicMock()
        broken_engine.get_entities_by_device.side_effect = RuntimeError("engine down")
        service._engine = broken_engine  # noqa: SLF001 — проверка пути отказа

        with patch("src.adapters.home_assistant.rest_client.HARestClient") as client_class:
            client = AsyncMock()
            client.connect_to_ha = AsyncMock(return_value=True)
            client.fetch_devices = AsyncMock(return_value=[])
            client.__aenter__ = AsyncMock(return_value=client)
            client.__aexit__ = AsyncMock(return_value=None)
            client_class.return_value = client

            await service.sync_devices_from_source(source_id)

        devices = await service.get_all_devices()
        assert devices[0].status == "removed_from_ha"
        assert broken_engine.get_entities_by_device.called

    def test_tombstone_should_track_removed_devices(self) -> None:
        """Удалённое устройство опознаётся как «уже удалённое»."""
        service = DeviceService(event_bus=MagicMock())
        device = _device("light.byebye")
        device_id = device.id
        service._devices[device_id] = device  # noqa: SLF001 — прямая установка в кэш

        assert service.was_device_deleted(device_id) is False

    @pytest.mark.asyncio
    async def test_remove_device_should_record_tombstone(self) -> None:
        """После удаления устройство опознаётся как удалённое."""
        service = _service_with_source(uuid4())
        device = _device("light.tombstone")
        await service.add_device(device)

        await service.remove_device(device.id)

        assert service.was_device_deleted(device.id) is True
        assert await service.get_device(device.id) is None


class TestDiscoveryScan:
    """Сканирование источника через WebSocket-адаптер."""

    @pytest.mark.asyncio
    async def test_scan_devices_should_paginate_and_filter(self) -> None:
        """Сканирование отдаёт страницы и соблюдает фильтры."""
        adapter = AsyncMock()
        adapter.is_connected = True
        ws_client = AsyncMock()
        ws_client.get_states = AsyncMock(
            return_value=[
                {"entity_id": "light.a", "state": "on", "attributes": {}},
                {"entity_id": "light.b", "state": "off", "attributes": {}},
                {"entity_id": "switch.c", "state": "on", "attributes": {}},
                {"entity_id": "automation.system", "state": "on", "attributes": {}},
            ]
        )
        adapter._ws_client = ws_client  # noqa: SLF001 — адаптер хранит клиента внутри

        service = DeviceDiscoveryService(adapter)

        first_page = await service.scan_devices(page=1, page_size=2)
        light_only = await service.scan_devices(page=1, page_size=10, filter_domain="light")
        switch_only = await service.scan_devices(page=1, page_size=10, filter_domain="switch")

        assert first_page["total"] == 3, "Системные сущности не считаются устройствами"
        assert len(first_page["devices"]) == 2, "Постраничный вывод соблюдается"
        assert [d["entity_id"] for d in light_only["devices"]] == ["light.a", "light.b"]
        assert [d["entity_id"] for d in switch_only["devices"]] == ["switch.c"]
        assert "by_domain" in first_page

    @pytest.mark.asyncio
    async def test_scan_devices_should_require_connection(self) -> None:
        """Без подключения к Home Assistant сканирование невозможно."""
        adapter = AsyncMock()
        adapter.is_connected = False
        service = DeviceDiscoveryService(adapter)

        with pytest.raises(RuntimeError, match="not connected"):
            await service.scan_devices()
