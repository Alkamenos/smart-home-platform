"""Тесты публичного перестроения маппинга EventRouter (spec 006, FR-015).

Раньше маппинг «датчик → автоматика» строился только в конструкторе, удалить
или пересчитать его нельзя было: новое устройство не получало событий, а
осиротевшие записи удалённых устройств оставались навсегда.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import (  # noqa: E402
    AutomationDomainRules,
    AutomationRules,
    BehaviorConfig,
    Dashboard,
    DeviceConfig,
    FSMDefinition,
    InstanceConfig,
    Manifest,
    RoomConfig,
)
from core.events.event_router import EventRouter  # noqa: E402


class MockFSMEngine:
    """Минимальная замена движка: хранит определения и отдаёт сущности устройства."""

    def __init__(self) -> None:
        self._definitions: dict[str, FSMDefinition] = {}

    def register_definition(self, definition: FSMDefinition) -> None:
        """Регистрирует определение автоматики."""
        self._definitions[definition.entity_id] = definition

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Имитация триггера автоматики."""
        return True

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Возвращает идентификаторы автоматик устройства по префиксу."""
        return [eid for eid in self._definitions if eid.startswith(f"{device_id}_")]


def _manifest_with_device(device_id: str, room_id: str = "kitchen") -> Manifest:
    """Собирает манифест с одной комнатой и одним устройством.

    Args:
        device_id: Идентификатор устройства.
        room_id: Идентификатор комнаты.

    Returns:
        Модель манифеста.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="test-instance",
            name="Test Instance",
            owner="test-owner",
            created_at="2024-01-01T00:00:00Z",
        ),
        rooms=[
            RoomConfig(
                id=room_id,
                name="Kitchen",
                sensors={"motion": "binary_sensor.kitchen_motion"},
                devices=[
                    DeviceConfig(
                        id=device_id,
                        type="light",
                        behaviors=[BehaviorConfig(template="lighting", priority=10)],
                    ),
                ],
            ),
        ],
        automation_rules=AutomationRules(
            lighting=AutomationDomainRules(motion_enabled=True, schedule_enabled=True),
            global_manual_lockout_min=0,
        ),
        dashboard=Dashboard(title="Test Dashboard"),
    )


def _register(router: EventRouter, device_id: str) -> None:
    """Регистрирует определение автоматики для устройства.

    Args:
        router: Маршрутизатор событий.
        device_id: Идентификатор устройства.
    """
    router._engine.register_definition(  # type: ignore[attr-defined]  # noqa: SLF001
        FSMDefinition(
            entity_id=f"{device_id}_lighting_10",
            initial_state="OFF",
            states={},
            transitions={},
        )
    )


class TestEventRouterRebuild:
    """Тесты метода rebuild()."""

    def test_rebuild_should_include_new_device_when_called_after_registration(self) -> None:
        """rebuild() должен добавить маппинги для устройства, добавленного после конструирования."""
        engine = MockFSMEngine()
        router = EventRouter(_manifest_with_device("light.kitchen"), engine)

        assert router.get_mapping_for_sensor("binary_sensor.kitchen_motion") == []

        _register(router, "light.kitchen")
        router.rebuild(_manifest_with_device("light.kitchen"))

        mappings = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        # Сенсор движения даёт два события: motion_detected и motion_cleared
        assert {fsm_id for fsm_id, _event in mappings} == {"light.kitchen_lighting_10"}
        assert len(mappings) == 2

    def test_rebuild_should_drop_mappings_of_removed_device(self) -> None:
        """rebuild() должен убрать маппинги устройства, которого больше нет в манифесте."""
        engine = MockFSMEngine()
        router = EventRouter(_manifest_with_device("light.kitchen"), engine)
        _register(router, "light.kitchen")
        router.rebuild(_manifest_with_device("light.kitchen"))

        assert len(router.get_mapping_for_sensor("binary_sensor.kitchen_motion")) == 2

        # Устройство убрано из манифеста, но его определение ещё в движке
        router.rebuild(
            Manifest(
                version=1,
                instance=InstanceConfig(
                    id="test-instance",
                    name="Test Instance",
                    owner="test-owner",
                    created_at="2024-01-01T00:00:00Z",
                ),
                rooms=[],
                automation_rules=AutomationRules(global_manual_lockout_min=0),
                dashboard=Dashboard(title="Test Dashboard"),
            )
        )

        assert router.get_mapping_for_sensor("binary_sensor.kitchen_motion") == []

    def test_rebuild_should_be_idempotent_when_called_twice(self) -> None:
        """Повторный rebuild() не должен дублировать маппинги."""
        engine = MockFSMEngine()
        router = EventRouter(_manifest_with_device("light.kitchen"), engine)
        _register(router, "light.kitchen")

        manifest = _manifest_with_device("light.kitchen")
        router.rebuild(manifest)
        router.rebuild(manifest)

        mappings = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        assert len(mappings) == 2  # motion_detected + motion_cleared
        assert len({(fsm_id, event) for fsm_id, event in mappings}) == 2

    def test_rebuild_should_update_manifest_reference(self) -> None:
        """rebuild() должен переключать роутер на переданный манифест."""
        engine = MockFSMEngine()
        router = EventRouter(_manifest_with_device("light.kitchen"), engine)

        updated = _manifest_with_device("light.kitchen", room_id="living_room")
        updated.rooms[0].sensors = {"motion": "binary_sensor.living_room_motion"}
        _register(router, "light.kitchen")
        router.rebuild(updated)

        assert router.get_mapping_for_sensor("binary_sensor.living_room_motion")
        assert router.get_mapping_for_sensor("binary_sensor.kitchen_motion") == []

    def test_rebuild_should_use_engine_state_when_manifest_omitted(self) -> None:
        """Без манифеста rebuild() переиспользует текущий (в т.ч. обновлённый) манифест."""
        engine = MockFSMEngine()
        manifest = _manifest_with_device("light.kitchen")
        router = EventRouter(manifest, engine)
        _register(router, "light.kitchen")

        # Мутация того же объекта, который роутер уже держит
        manifest.rooms[0].devices.append(
            DeviceConfig(
                id="light.hall",
                type="light",
                behaviors=[BehaviorConfig(template="lighting", priority=10)],
            )
        )
        _register(router, "light.hall")

        router.rebuild()

        fsm_ids = {
            fsm_id
            for fsm_id, _event in router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        }
        assert fsm_ids == {"light.kitchen_lighting_10", "light.hall_lighting_10"}
