"""
Unit tests for EventRouter module (room-based architecture).

Tests verify that:
1. Sensor events from room.sensors route to all devices in that room
2. Motion sensor on/off triggers correct FSM events
3. Same sensor can be referenced from multiple rooms
4. Unknown sensor does not cause errors
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import os
import sys
from typing import Any

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import (
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
from core.event_router import EventRouter


class MockFSMEngine:
    """Mock FSMEngine for testing EventRouter."""

    def __init__(self) -> None:
        self._definitions: dict[str, FSMDefinition] = {}
        self.trigger_calls: list[tuple[str, str, dict[str, Any]]] = []

    def register_definition(self, definition: FSMDefinition) -> None:
        """Register an FSM definition."""
        self._definitions[definition.entity_id] = definition

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Mock trigger that records calls."""
        self.trigger_calls.append((entity_id, event, external_ctx or {}))
        return True

    def get_entities_by_device(self, device_id: str) -> list[str]:
        """Get all FSM entity IDs belonging to a specific device."""
        return [
            entity_id for entity_id in self._definitions if entity_id.startswith(f"{device_id}_")
        ]


def create_test_manifest() -> Manifest:
    """Create a minimal test manifest with room-based structure."""
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
                id="kitchen",
                name="Kitchen",
                sensors={
                    "motion": "binary_sensor.kitchen_motion",
                    "humidity": "sensor.kitchen_humidity",
                    "temperature": "sensor.kitchen_temperature",
                },
                devices=[
                    DeviceConfig(
                        id="light.kitchen",
                        type="light",
                        behaviors=[
                            BehaviorConfig(
                                template="lighting",
                                priority=10,
                                params={
                                    "motion_timeout_sec": 300,
                                    "brightness": 255,
                                },
                            ),
                        ],
                    ),
                ],
            ),
        ],
        automation_rules=AutomationRules(
            lighting=AutomationDomainRules(
                motion_enabled=True,
                schedule_enabled=True,
                manual_lockout_min=5,
            ),
            global_manual_lockout_min=0,
        ),
        dashboard=Dashboard(title="Test Dashboard"),
    )


class TestEventRouterMapping:
    """Tests for EventRouter mapping building from room.sensors."""

    def test_build_mapping_motion_sensor(self) -> None:
        """Motion sensor in room.sensors creates motion_detected and motion_cleared mappings."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")

        assert len(mappings) == 2
        assert ("light.kitchen_lighting_10", "motion_detected") in mappings
        assert ("light.kitchen_lighting_10", "motion_cleared") in mappings

    def test_build_mapping_humidity_sensor(self) -> None:
        """Humidity sensor in room.sensors creates humidity_changed mapping."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register BOTH FSMs (light + ventilation)
        engine.register_definition(
            FSMDefinition(
                entity_id="light.kitchen_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )
        engine.register_definition(
            FSMDefinition(
                entity_id="fan.kitchen_ventilation_5",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )

        # Add ventilation device to kitchen
        manifest.rooms[0].devices.append(
            DeviceConfig(
                id="fan.kitchen_ventilation",
                type="ventilation",
                behaviors=[
                    BehaviorConfig(template="humidity_ventilation", priority=5),
                ],
            )
        )

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("sensor.kitchen_humidity")

        assert len(mappings) == 2
        assert ("fan.kitchen_ventilation_5", "humidity_changed") in mappings
        assert ("light.kitchen_lighting_10", "humidity_changed") in mappings

    def test_build_mapping_temperature_sensor(self) -> None:
        """Temperature sensor in room.sensors creates temperature_changed mapping."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register BOTH FSMs (light + climate)
        engine.register_definition(
            FSMDefinition(
                entity_id="light.kitchen_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )
        engine.register_definition(
            FSMDefinition(
                entity_id="climate.kitchen_climate_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )

        # Add climate device to kitchen
        manifest.rooms[0].devices.append(
            DeviceConfig(
                id="climate.kitchen_climate",
                type="climate",
                behaviors=[
                    BehaviorConfig(template="climate", priority=10),
                ],
            )
        )

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("sensor.kitchen_temperature")

        assert len(mappings) == 2
        assert ("climate.kitchen_climate_10", "temperature_changed") in mappings
        assert ("light.kitchen_lighting_10", "temperature_changed") in mappings

    def test_shared_sensor_across_rooms(self) -> None:
        """Same sensor entity can trigger devices in multiple rooms."""
        manifest = Manifest(
            version=1,
            instance=InstanceConfig(id="test", name="Test"),
            rooms=[
                RoomConfig(
                    id="hallway",
                    name="Hallway",
                    sensors={"motion": "binary_sensor.hallway_motion"},
                    devices=[
                        DeviceConfig(
                            id="light.hallway",
                            type="light",
                            behaviors=[
                                BehaviorConfig(template="lighting", priority=10),
                            ],
                        ),
                    ],
                ),
                RoomConfig(
                    id="kitchen",
                    name="Kitchen",
                    sensors={"motion": "binary_sensor.hallway_motion"},  # shared
                    devices=[
                        DeviceConfig(
                            id="light.kitchen",
                            type="light",
                            behaviors=[
                                BehaviorConfig(template="lighting", priority=10),
                            ],
                        ),
                    ],
                ),
            ],
        )
        engine = MockFSMEngine()

        engine.register_definition(
            FSMDefinition(
                entity_id="light.hallway_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )
        engine.register_definition(
            FSMDefinition(
                entity_id="light.kitchen_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("binary_sensor.hallway_motion")

        # Sensor should route to devices in BOTH rooms
        assert len(mappings) == 4  # 2 rooms × 2 events
        assert ("light.hallway_lighting_10", "motion_detected") in mappings
        assert ("light.hallway_lighting_10", "motion_cleared") in mappings
        assert ("light.kitchen_lighting_10", "motion_detected") in mappings
        assert ("light.kitchen_lighting_10", "motion_cleared") in mappings


class TestEventRouterRouting:
    """Tests for EventRouter route_state_change method."""

    @pytest.mark.asyncio
    async def test_route_motion_detected_event(self) -> None:
        """Motion sensor ON triggers motion_detected on room devices."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        assert len(engine.trigger_calls) == 1
        entity_id, event, ctx = engine.trigger_calls[0]
        assert entity_id == "light.kitchen_lighting_10"
        assert event == "motion_detected"
        assert ctx["new_state"] == "on"
        assert ctx["old_state"] == "off"
        assert ctx["entity_id"] == "binary_sensor.kitchen_motion"

    @pytest.mark.asyncio
    async def test_route_motion_cleared_event(self) -> None:
        """Motion sensor OFF triggers motion_cleared on room devices."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="off",
            old_state="on",
            context={},
        )

        assert len(engine.trigger_calls) == 1
        entity_id, event, ctx = engine.trigger_calls[0]
        assert entity_id == "light.kitchen_lighting_10"
        assert event == "motion_cleared"

    @pytest.mark.asyncio
    async def test_unknown_sensor_no_error(self) -> None:
        """Unknown sensor_id does not cause errors."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.unknown_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        assert len(engine.trigger_calls) == 0

    @pytest.mark.asyncio
    async def test_motion_detected_not_triggered_on_off_state(self) -> None:
        """motion_detected is NOT triggered when new_state is 'off'."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="off",
            old_state="on",
            context={},
        )

        assert len(engine.trigger_calls) == 1
        _, event, _ = engine.trigger_calls[0]
        assert event == "motion_cleared"

    @pytest.mark.asyncio
    async def test_motion_cleared_not_triggered_on_on_state(self) -> None:
        """motion_cleared is NOT triggered when new_state is 'on'."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        assert len(engine.trigger_calls) == 1
        _, event, _ = engine.trigger_calls[0]
        assert event == "motion_detected"

    @pytest.mark.asyncio
    async def test_shared_sensor_triggers_all_rooms(self) -> None:
        """Shared sensor triggers FSMs in all rooms that reference it."""
        manifest = Manifest(
            version=1,
            instance=InstanceConfig(id="test", name="Test"),
            rooms=[
                RoomConfig(
                    id="hallway",
                    name="Hallway",
                    sensors={"motion": "binary_sensor.hallway_motion"},
                    devices=[
                        DeviceConfig(
                            id="light.hallway",
                            type="light",
                            behaviors=[BehaviorConfig(template="lighting", priority=10)],
                        ),
                    ],
                ),
                RoomConfig(
                    id="kitchen",
                    name="Kitchen",
                    sensors={"motion": "binary_sensor.hallway_motion"},
                    devices=[
                        DeviceConfig(
                            id="light.kitchen",
                            type="light",
                            behaviors=[BehaviorConfig(template="lighting", priority=10)],
                        ),
                    ],
                ),
            ],
        )
        engine = MockFSMEngine()

        engine.register_definition(
            FSMDefinition(
                entity_id="light.hallway_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )
        engine.register_definition(
            FSMDefinition(
                entity_id="light.kitchen_lighting_10",
                initial_state="OFF",
                states=("OFF", "ON"),
                transitions=(),
            )
        )

        router = EventRouter(manifest, engine)

        await router.route_state_change(
            entity_id="binary_sensor.hallway_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        # Both hallway and kitchen should receive motion_detected
        assert len(engine.trigger_calls) == 2
        entities = {call[0] for call in engine.trigger_calls}
        events = {call[1] for call in engine.trigger_calls}
        assert entities == {"light.hallway_lighting_10", "light.kitchen_lighting_10"}
        assert events == {"motion_detected"}


class TestEventRouterGetMapping:
    """Tests for get_mapping_for_sensor method."""

    def test_get_mapping_returns_copy(self) -> None:
        """get_mapping_for_sensor returns a copy, not internal reference."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        mappings1 = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")
        mappings2 = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")

        assert mappings1 == mappings2
        assert mappings1 is not mappings2

    def test_get_mapping_unknown_sensor_returns_empty_list(self) -> None:
        """Unknown sensor returns empty list."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        router = EventRouter(manifest, engine)

        mappings = router.get_mapping_for_sensor("binary_sensor.nonexistent")

        assert mappings == []
        assert isinstance(mappings, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
