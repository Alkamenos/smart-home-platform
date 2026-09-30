"""Тесты записи манифеста из обнаружения устройств (spec 006, T026).

Раньше `discovery_service` писал сырой YAML и делал резервную копию уже после
мутации, а повторное применение добавляло дубли устройств. Проверяем, что
запись идёт через `ManifestStore`, снимок соответствует состоянию до
изменений, а повторное применение не плодит дубли.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml
from src.core.discovery.discovery_service import DeviceDiscoveryService


@pytest.fixture
def manifest_path() -> Iterator[Path]:
    """Копия реального манифеста во временном каталоге.

    Yields:
        Путь к файлу манифеста.
    """
    project_root = Path(__file__).resolve().parent.parent.parent
    source = project_root / "instances" / "leonids_house" / "manifest.yaml"
    work_dir = Path(tempfile.mkdtemp(prefix="discovery_manifest_"))
    target = work_dir / "manifest.yaml"
    shutil.copy(source, target)
    try:
        yield target
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _selections(*entity_ids: str) -> list[dict[str, Any]]:
    """Формирует выборку устройств для применения.

    Args:
        entity_ids: Идентификаторы сущностей.

    Returns:
        Список выборок.
    """
    return [
        {
            "device_entity_id": entity_id,
            "target_room": "hall",
            "behavior_template": "lighting",
            "behavior_params": {},
        }
        for entity_id in entity_ids
    ]


def _load(manifest_path: Path) -> dict[str, Any]:
    """Читает манифест с диска.

    Args:
        manifest_path: Путь к манифесту.

    Returns:
        Данные манифеста.
    """
    with open(manifest_path) as f:
        return yaml.safe_load(f) or {}


def _devices_of(manifest: dict[str, Any], room_id: str) -> list[str]:
    """Возвращает идентификаторы устройств комнаты.

    Args:
        manifest: Данные манифеста.
        room_id: Идентификатор комнаты.

    Returns:
        Список идентификаторов устройств.
    """
    room = next((r for r in manifest.get("rooms", []) if r["id"] == room_id), None)
    return [d["id"] for d in (room or {}).get("devices", [])]


class TestDiscoveryManifestWrite:
    """Запись манифеста из мастера обнаружения."""

    @pytest.mark.asyncio
    async def test_apply_should_write_manifest_via_store(self, manifest_path: Path) -> None:
        """Применение записывает манифест и оставляет снимок в файле."""
        service = DeviceDiscoveryService(AsyncMock())

        result = await service.apply_selective(_selections("light.new_one"), str(manifest_path))

        assert result["devices_added"] == 1
        assert result["failed"] == 0
        assert "light.new_one" in _devices_of(_load(manifest_path), "hall")
        assert (manifest_path.parent / "manifest.yaml.bak").exists()

    @pytest.mark.asyncio
    async def test_backup_should_contain_state_before_changes(self, manifest_path: Path) -> None:
        """Резервная копия — снимок ДО применения, а не после."""
        before = _devices_of(_load(manifest_path), "hall")
        service = DeviceDiscoveryService(AsyncMock())

        await service.apply_selective(_selections("light.brand_new"), str(manifest_path))

        with open(f"{manifest_path}.bak") as f:
            backup = yaml.safe_load(f) or {}
        assert _devices_of(backup, "hall") == before
        assert "light.brand_new" not in _devices_of(backup, "hall")

    @pytest.mark.asyncio
    async def test_repeated_apply_should_not_duplicate_devices(self, manifest_path: Path) -> None:
        """Повторное применение не создаёт дублей (идемпотентность)."""
        service = DeviceDiscoveryService(AsyncMock())

        first = await service.apply_selective(_selections("light.twice"), str(manifest_path))
        second = await service.apply_selective(_selections("light.twice"), str(manifest_path))

        assert first["devices_added"] == 1
        assert second["devices_added"] == 0
        assert second["already_present"] == 1
        assert _devices_of(_load(manifest_path), "hall").count("light.twice") == 1

    @pytest.mark.asyncio
    async def test_dry_run_should_not_touch_manifest(self, manifest_path: Path) -> None:
        """Тестовый запуск не меняет файл и не создаёт снимок."""
        before = manifest_path.read_text()
        service = DeviceDiscoveryService(AsyncMock())

        result = await service.apply_selective(
            _selections("light.dry"), str(manifest_path), dry_run=True
        )

        assert result["dry_run"] is True
        assert result["would_add"] == 1
        assert manifest_path.read_text() == before
        assert not (manifest_path.parent / "manifest.yaml.bak").exists()

    @pytest.mark.asyncio
    async def test_apply_should_use_injected_store(self, manifest_path: Path) -> None:
        """Применение обновляет переданное хранилище, а не отдельную копию файла."""
        from src.core.persistence.manifest_store import ManifestStore

        store = ManifestStore(str(manifest_path))
        store.load()
        service = DeviceDiscoveryService(AsyncMock(), manifest_store=store)

        await service.apply_selective(_selections("light.shared_store"), str(manifest_path))

        assert "light.shared_store" in [
            d.id for d in store.current.get_room_for_device("light.shared_store").devices
        ]  # type: ignore[union-attr]
        assert "light.shared_store" in _devices_of(_load(manifest_path), "hall")

    @pytest.mark.asyncio
    async def test_bulk_apply_should_use_store(self, manifest_path: Path) -> None:
        """Массовое применение тоже идёт через хранилище и не дублирует."""
        service = DeviceDiscoveryService(AsyncMock())
        service.scan_devices = AsyncMock(  # type: ignore[method-assign]
            return_value={
                "devices": [
                    {
                        "entity_id": "light.bulk_one",
                        "category": "lighting",
                        "domain": "light",
                        "area_id": "hall",
                        "auto_apply": True,
                        "suggested_behavior": "lighting",
                    }
                ]
            }
        )
        request = _bulk_request()

        first = await service.bulk_apply(request, str(manifest_path))
        second = await service.bulk_apply(request, str(manifest_path))

        assert first["devices_added"] == 1
        assert second["devices_added"] == 0
        assert _devices_of(_load(manifest_path), "hall").count("light.bulk_one") == 1

    @pytest.mark.asyncio
    async def test_sensor_slot_should_not_be_overwritten(self, manifest_path: Path) -> None:
        """Занятый слот датчика не перетирается вторым устройством."""
        from src.core.models.manifest import Manifest

        service = DeviceDiscoveryService(AsyncMock())
        store = service._store_for(str(manifest_path))  # noqa: SLF001 — проверка внутреннего пути
        assert isinstance(store.current, Manifest)
        room = service._room_manifest(store.current, "hall")  # noqa: SLF001
        room.sensors = {"motion": "binary_sensor.hall_motion"}
        store.mark_changed()
        store.save()

        result = await service.apply_selective(
            [
                {
                    "device_entity_id": "binary_sensor.other_motion",
                    "target_room": "hall",
                    "category": "motion_sensor",
                }
            ],
            str(manifest_path),
        )

        assert result["devices_added"] == 0
        assert result["already_present"] == 1
        with open(manifest_path) as f:
            hall = next(r for r in (yaml.safe_load(f) or {}).get("rooms", []) if r["id"] == "hall")
        assert hall["sensors"]["motion"] == "binary_sensor.hall_motion"


def _bulk_request() -> Any:
    """Создаёт запрос массового применения с автоприменением освещения.

    Returns:
        Запрос массового применения.
    """
    from src.core.discovery.models import BulkApplyRequest

    return BulkApplyRequest(
        include_all=False,
        auto_apply_lighting=True,
        auto_apply_climate=False,
        auto_apply_ventilation=False,
        exclude_entities=[],
        dry_run=False,
    )
