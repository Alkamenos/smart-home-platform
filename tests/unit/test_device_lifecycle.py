"""Тесты транзакции жизненного цикла устройства (spec 006, US1).

Сервис жизненного цикла — единственная точка, которая выполняет операцию
целиком: манифест → постоянное хранилище → runtime (кэш/индекс) → машины
состояний → карта маршрутизации → аудит (D-003, D-012).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from src.core.action_handlers import register_all_actions
from src.core.events.event_bus import EventBus
from src.core.events.event_router import EventRouter
from src.core.fsm.engine import FSMEngine
from src.core.fsm.factory import FSMFactory
from src.core.models.manifest import (
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    Dashboard,
    DeviceConfig,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from src.core.persistence.manager import PersistenceManager
from src.core.registry import Registry
from src.services.device_lifecycle import DeviceLifecycleService
from src.services.device_service import DeviceService

from tests.helpers.device_factory import make_device, make_source


@pytest.fixture
def persistence(tmp_path: Path) -> PersistenceManager:
    """Менеджер хранения в изолированном каталоге.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Экземпляр PersistenceManager.
    """
    return PersistenceManager(data_dir=tmp_path / "data")


@pytest.fixture
def manifest() -> Manifest:
    """Манифест из одной комнаты с датчиком движения.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="test-house",
            name="Test House",
            owner="test-owner",
            created_at="2026-01-01T00:00:00Z",
        ),
        rooms=[
            RoomConfig(
                id="kitchen",
                name="Kitchen",
                sensors={"motion": "binary_sensor.kitchen_motion"},
                devices=[
                    DeviceConfig(
                        id="light.kitchen",
                        type="light",
                        name="Kitchen Light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={"motion_sensor": "binary_sensor.kitchen_motion"},
                            )
                        ],
                    )
                ],
            )
        ],
        automation_rules=AutomationRules(
            lighting=AutomationDomainRules(motion_enabled=True),
            global_manual_lockout_min=0,
        ),
        dashboard=Dashboard(title="Test"),
    )


@pytest.fixture
def engine() -> FSMEngine:
    """Движок машин состояний без внешних зависимостей.

    Returns:
        Экземпляр FSMEngine.
    """
    return FSMEngine()


@pytest.fixture
def factory(engine: FSMEngine) -> FSMFactory:
    """Фабрика машин состояний с зарегистрированными действиями.

    Args:
        engine: Движок машин состояний.

    Returns:
        Экземпляр FSMFactory.
    """
    registry = Registry()
    register_all_actions(registry)
    return FSMFactory(engine=engine, registry=registry, event_bus=None)


@pytest.fixture
def lifecycle(
    persistence: PersistenceManager,
    engine: FSMEngine,
    factory: FSMFactory,
    manifest: Manifest,
) -> DeviceLifecycleService:
    """Сервис жизненного цикла на реальных компонентах ядра.

    Args:
        persistence: Менеджер хранения.
        engine: Движок машин состояний.
        factory: Фабрика машин состояний.
        manifest: Манифест.

    Returns:
        Экземпляр DeviceLifecycleService.
    """
    device_service = DeviceService(
        event_bus=EventBus(),
        persistence_module=persistence,
        ha_adapter=AsyncMock(),
    )
    return DeviceLifecycleService(
        manifest=manifest,
        device_service=device_service,
        factory=factory,
        engine=engine,
        event_router=EventRouter(manifest, engine),
        persistence=persistence,
    )


def _fsm_ids_of(engine: FSMEngine, prefix: str) -> list[str]:
    """Возвращает идентификаторы автоматик устройства.

    Args:
        engine: Движок машин состояний.
        prefix: Префикс идентификатора устройства.

    Returns:
        Отсортированный список идентификаторов.
    """
    return sorted(eid for eid in engine.get_all_states() if eid.startswith(f"{prefix}_"))


class TestDeviceLifecycleAdd:
    """Тесты добавления устройства (FR-014, FR-028)."""

    async def test_add_device_should_register_fsm_and_route_sensor(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Добавленное устройство получает автоматику и маппинг датчика (FR-015, SC-002)."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")

        assert _fsm_ids_of(lifecycle.engine, "light.kitchen") == ["light.kitchen_lighting_10"]
        mappings = lifecycle.event_router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        assert {fsm_id for fsm_id, _event in mappings} == {"light.kitchen_lighting_10"}

    async def test_add_device_should_persist_and_be_listed(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Устройство сохраняется и видно в списке сервиса (FR-001, FR-003, FR-004)."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")

        assert await lifecycle.device_service.get_device(device.id) is not None
        assert await lifecycle.persistence.devices.load_device(device.id) is not None

    async def test_add_device_should_add_entry_to_manifest(
        self, lifecycle: DeviceLifecycleService, manifest: Manifest
    ) -> None:
        """Состав манифеста обновляется (FR-004)."""
        device = make_device(ha_entity_id="light.hall", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")

        assert any(d.id == "light.hall" for d in manifest.rooms[0].devices)

    async def test_add_device_should_record_audit_event(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Операция фиксируется в журнале (FR-028)."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")

        events = await lifecycle.persistence.device_sync_events.list_events(device.id)
        assert [event.action for event in events] == ["device_added"]
        assert events[0].user_id == "admin_user"

    async def test_add_device_should_use_given_user_id_in_audit(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """В записи сохраняется инициатор, переданный вызывающим."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen", user_id="operator")

        events = await lifecycle.persistence.device_sync_events.list_events(device.id)
        assert events[0].user_id == "operator"


class TestDeviceLifecycleIdempotency:
    """Тесты идемпотентности повторного применения (FR-008, FR-018)."""

    async def test_add_device_twice_should_not_duplicate_fsm(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Повторное добавление не создаёт вторую автоматику."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")
        await lifecycle.add_device(device, room_id="kitchen")

        assert _fsm_ids_of(lifecycle.engine, "light.kitchen") == ["light.kitchen_lighting_10"]

    async def test_add_device_twice_should_not_duplicate_manifest_entry(
        self, lifecycle: DeviceLifecycleService, manifest: Manifest
    ) -> None:
        """В манифесте остаётся одна запись устройства."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")
        await lifecycle.add_device(device, room_id="kitchen")

        assert len([d for d in manifest.rooms[0].devices if d.id == "light.kitchen"]) == 1

    async def test_add_device_twice_should_not_duplicate_stored_device(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """В постоянном хранилище остаётся одна запись устройства."""
        source_id = make_source().id
        first = make_device(ha_entity_id="light.kitchen", source_id=source_id)
        second = make_device(ha_entity_id="light.kitchen", source_id=source_id, name="Новое имя")

        await lifecycle.add_device(first, room_id="kitchen")
        await lifecycle.add_device(second, room_id="kitchen")

        stored = await lifecycle.device_service.get_all_devices()
        assert len(stored) == 1
        assert stored[0].name == "Новое имя"


class TestDeviceLifecycleRollback:
    """Тесты компенсации при сбое (D-012)."""

    async def test_add_device_should_roll_back_manifest_when_storage_fails(
        self, lifecycle: DeviceLifecycleService, manifest: Manifest
    ) -> None:
        """Сбой записи в хранилище откатывает манифест и не оставляет автоматику."""
        original_devices = [d.id for d in manifest.rooms[0].devices]
        lifecycle.persistence.devices.save_device = AsyncMock(side_effect=OSError("disk full"))

        with pytest.raises(RuntimeError, match="хранилищ"):
            await lifecycle.add_device(
                make_device(ha_entity_id="light.hall", source_id=make_source().id),
                room_id="kitchen",
            )

        assert [d.id for d in manifest.rooms[0].devices] == original_devices
        assert _fsm_ids_of(lifecycle.engine, "light.hall") == []

    async def test_add_device_should_reject_unknown_room(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Несуществующая комната отклоняется с понятной ошибкой (FR-007)."""
        with pytest.raises(ValueError, match="омната"):
            await lifecycle.add_device(
                make_device(ha_entity_id="light.hall", source_id=make_source().id),
                room_id="no_such_room",
            )

    async def test_add_device_should_keep_data_when_fsm_registration_fails(
        self, lifecycle: DeviceLifecycleService, manifest: Manifest
    ) -> None:
        """Ошибка на шаге машин состояний не теряет данные, а попадает в журнал (D-012)."""
        lifecycle.engine.register_definition = MagicMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("fsm registration failed")
        )
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)

        await lifecycle.add_device(device, room_id="kitchen")

        assert any(d.id == "light.kitchen" for d in manifest.rooms[0].devices)
        assert await lifecycle.persistence.devices.load_device(device.id) is not None


class TestDeviceLifecycleUpdate:
    """Тесты изменения устройства."""

    async def test_update_device_should_replace_fsm_set(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Изменение состава поведений пересоздаёт автоматику без дублей."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)
        await lifecycle.add_device(device, room_id="kitchen")

        await lifecycle.update_device(
            device,
            room_id="kitchen",
            behaviors=[
                BehaviorConfig(template="lighting", priority=10),
                BehaviorConfig(template="generic_switch", priority=20),
            ],
        )

        assert _fsm_ids_of(lifecycle.engine, "light.kitchen") == [
            "light.kitchen_generic_switch_20",
            "light.kitchen_lighting_10",
        ]

    async def test_update_device_should_record_audit_event(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Изменение фиксируется в журнале."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)
        await lifecycle.add_device(device, room_id="kitchen")

        await lifecycle.update_device(
            device, room_id="kitchen", behaviors=[BehaviorConfig(template="lighting", priority=10)]
        )

        events = await lifecycle.persistence.device_sync_events.list_events(device.id)
        assert [event.action for event in events] == ["device_updated", "device_added"]


class TestDeviceLifecycleDeactivate:
    """Тесты снятия автоматики устройства (FR-017)."""

    async def test_deactivate_device_should_unregister_fsm_and_reroute(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Деактивация снимает автоматику и убирает её из маршрутизации."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)
        await lifecycle.add_device(device, room_id="kitchen")

        await lifecycle.deactivate_device(device)

        assert _fsm_ids_of(lifecycle.engine, "light.kitchen") == []
        mappings = lifecycle.event_router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        assert {fsm_id for fsm_id, _event in mappings} == set()

    async def test_deactivate_device_should_keep_device_in_storage(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Деактивация не удаляет устройство: конфигурация сохраняется (FR-022)."""
        device = make_device(ha_entity_id="light.kitchen", source_id=make_source().id)
        await lifecycle.add_device(device, room_id="kitchen")

        await lifecycle.deactivate_device(device)

        assert await lifecycle.persistence.devices.load_device(device.id) is not None


class TestDeviceLifecycleStandalone:
    """Тесты автономного режима без машин состояний (конституция VI)."""

    async def test_add_device_should_work_without_engine_and_router(
        self, persistence: PersistenceManager, manifest: Manifest
    ) -> None:
        """Без движка и маршрутизатора устройство добавляется и сохраняется."""
        service = DeviceLifecycleService(
            manifest=manifest,
            device_service=DeviceService(
                event_bus=EventBus(), persistence_module=persistence, ha_adapter=AsyncMock()
            ),
            factory=None,
            engine=None,
            event_router=None,
            persistence=persistence,
        )
        device = make_device(ha_entity_id="light.hall", source_id=make_source().id)

        await service.add_device(device, room_id="kitchen")

        assert await persistence.devices.load_device(device.id) is not None
        assert any(d.id == "light.hall" for d in manifest.rooms[0].devices)

    async def test_audit_failure_should_not_break_operation(
        self, lifecycle: DeviceLifecycleService
    ) -> None:
        """Ошибка записи аудита не приводит к потере результата операции (FR-028)."""
        lifecycle.persistence.device_sync_events.append_event = AsyncMock(
            side_effect=OSError("history unavailable")
        )

        await lifecycle.add_device(
            make_device(ha_entity_id="light.kitchen", source_id=make_source().id),
            room_id="kitchen",
        )

        assert _fsm_ids_of(lifecycle.engine, "light.kitchen") == ["light.kitchen_lighting_10"]
