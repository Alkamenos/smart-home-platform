"""
Unit tests for EventRouter module.

Tests verify that:
1. Events from binary_sensor.kitchen_motion -> on trigger light.kitchen_lighting_10 with motion_detected
2. Events from binary_sensor.kitchen_motion -> off trigger light.kitchen_lighting_10 with motion_cleared
3. Unknown sensor_id does not cause errors
"""

import os

# Add parent directory to path
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from smart_home.core.event_router import EventRouter
from smart_home.core.fsm import FSMDefinition
from smart_home.core.models.manifest import (
    AutomationRules,
    BehaviorConfig,
    ClimateAutomation,
    Dashboard,
    InstanceInfo,
    LightingAutomation,
    LightMotionDevice,
    Manifest,
    VentilationAutomation,
    Zone,
)


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
            entity_id
            for entity_id in self._definitions.keys()
            if entity_id.startswith(f"{device_id}_")
        ]


def create_test_manifest() -> Manifest:
    """Create a minimal test manifest with a light_motion device."""
    return Manifest(
        version=1,
        instance=InstanceInfo(
            id="test-instance",
            name="Test Instance",
            owner="test-owner",
            created_at="2024-01-01T00:00:00Z",
        ),
        zones=[Zone(id="zone1", name="First Floor", floor=1)],
        devices=[
            LightMotionDevice(
                type="light_motion",
                id="light.kitchen",
                name="Kitchen Light",
                room="kitchen",
                behaviors=[
                    BehaviorConfig(
                        template="lighting",
                        priority=10,
                        params={
                            "motion_sensor": "binary_sensor.kitchen_motion",
                            "motion_timeout_sec": 300,
                            "schedule": "07:00-23:00",
                            "brightness": 255,
                        },
                    ),
                ],
            ),
        ],
        automation_rules=AutomationRules(
            lighting=LightingAutomation(
                motion_enabled=True,
                schedule_enabled=True,
                manual_lockout_min=5,
            ),
            climate=ClimateAutomation(
                safety_lockout_enabled=False,
                away_mode_enabled=False,
                manual_lockout_min=0,
            ),
            ventilation=VentilationAutomation(
                humidity_based=False,
                manual_lockout_min=0,
            ),
            global_manual_lockout_min=0,
        ),
        dashboard=Dashboard(
            title="Test Dashboard",
            show_history=True,
            show_climate=False,
            show_motion_sensors=True,
            history_days=7,
        ),
    )


class TestEventRouterMapping:
    """Tests for EventRouter mapping building."""

    def test_build_mapping_motion_sensor(self) -> None:
        """Test that motion_sensor in params creates correct mappings."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register a mock FSM definition so _get_fsm_entity_ids_for_device can find it
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        # Check mapping for motion sensor
        mappings = router.get_mapping_for_sensor("binary_sensor.kitchen_motion")

        assert len(mappings) == 2
        assert ("light.kitchen_lighting_10", "motion_detected") in mappings
        assert ("light.kitchen_lighting_10", "motion_cleared") in mappings

    def test_build_mapping_humidity_sensor(self) -> None:
        """Test that humidity_sensor in params creates correct mapping."""
        manifest = create_test_manifest()

        # Modify device to have humidity_sensor instead
        device = manifest.devices[0]
        device.behaviors = [
            BehaviorConfig(
                template="ventilation",
                priority=10,
                params={"humidity_sensor": "sensor.kitchen_humidity"},
            ),
        ]

        engine = MockFSMEngine()
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_ventilation_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("sensor.kitchen_humidity")

        assert len(mappings) == 1
        assert ("light.kitchen_ventilation_10", "humidity_changed") in mappings

    def test_build_mapping_temperature_sensor(self) -> None:
        """Test that sensor (temperature) in params creates correct mapping."""
        manifest = create_test_manifest()

        # Modify device to have temperature sensor
        device = manifest.devices[0]
        device.behaviors = [
            BehaviorConfig(
                template="climate",
                priority=10,
                params={"sensor": "sensor.kitchen_temperature"},
            ),
        ]

        engine = MockFSMEngine()
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_climate_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)
        mappings = router.get_mapping_for_sensor("sensor.kitchen_temperature")

        assert len(mappings) == 1
        assert ("light.kitchen_climate_10", "temperature_changed") in mappings

    def test_build_mapping_light_motion_device(self) -> None:
        """Test that light_motion device type creates manual_switch mappings."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register FSM definition
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        # Check mapping for the device itself (manual switch events)
        mappings = router.get_mapping_for_sensor("light.kitchen")

        assert len(mappings) == 2
        assert ("light.kitchen_lighting_10", "manual_switch_on") in mappings
        assert ("light.kitchen_lighting_10", "manual_switch_off") in mappings


class TestEventRouterRouting:
    """Tests for EventRouter route_state_change method."""

    @pytest.mark.asyncio
    async def test_route_motion_detected_event(self) -> None:
        """
        Test: событие binary_sensor.kitchen_motion -> on триггерит
        light.kitchen_lighting_10 с событием motion_detected.
        """
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register FSM definition
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        # Route state change: motion sensor turns ON
        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        # Verify trigger was called correctly
        assert len(engine.trigger_calls) == 1
        entity_id, event, ctx = engine.trigger_calls[0]
        assert entity_id == "light.kitchen_lighting_10"
        assert event == "motion_detected"
        assert ctx["new_state"] == "on"
        assert ctx["old_state"] == "off"
        assert ctx["entity_id"] == "binary_sensor.kitchen_motion"

    @pytest.mark.asyncio
    async def test_route_motion_cleared_event(self) -> None:
        """
        Test: событие binary_sensor.kitchen_motion -> off триггерит
        light.kitchen_lighting_10 с событием motion_cleared.
        """
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        # Register FSM definition
        fsm_def = FSMDefinition(
            entity_id="light.kitchen_lighting_10",
            initial_state="OFF",
            states=("OFF", "ON"),
            transitions=(),
        )
        engine.register_definition(fsm_def)

        router = EventRouter(manifest, engine)

        # Route state change: motion sensor turns OFF
        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="off",
            old_state="on",
            context={},
        )

        # Verify trigger was called correctly
        assert len(engine.trigger_calls) == 1
        entity_id, event, ctx = engine.trigger_calls[0]
        assert entity_id == "light.kitchen_lighting_10"
        assert event == "motion_cleared"
        assert ctx["new_state"] == "off"
        assert ctx["old_state"] == "on"
        assert ctx["entity_id"] == "binary_sensor.kitchen_motion"

    @pytest.mark.asyncio
    async def test_unknown_sensor_no_error(self) -> None:
        """
        Test: неизвестный sensor_id не вызывает ошибок.
        """
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        router = EventRouter(manifest, engine)

        # Route state change for unknown sensor - should not raise
        await router.route_state_change(
            entity_id="binary_sensor.unknown_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        # No triggers should have been called
        assert len(engine.trigger_calls) == 0

    @pytest.mark.asyncio
    async def test_motion_detected_not_triggered_on_off_state(self) -> None:
        """Test that motion_detected is NOT triggered when new_state is 'off'."""
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

        # When sensor goes OFF, motion_detected should NOT be triggered
        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="off",
            old_state="on",
            context={},
        )

        # Only motion_cleared should be triggered, not motion_detected
        assert len(engine.trigger_calls) == 1
        _, event, _ = engine.trigger_calls[0]
        assert event == "motion_cleared"

    @pytest.mark.asyncio
    async def test_motion_cleared_not_triggered_on_on_state(self) -> None:
        """Test that motion_cleared is NOT triggered when new_state is 'on'."""
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

        # When sensor goes ON, motion_cleared should NOT be triggered
        await router.route_state_change(
            entity_id="binary_sensor.kitchen_motion",
            new_state="on",
            old_state="off",
            context={},
        )

        # Only motion_detected should be triggered, not motion_cleared
        assert len(engine.trigger_calls) == 1
        _, event, _ = engine.trigger_calls[0]
        assert event == "motion_detected"


class TestEventRouterGetMapping:
    """Tests for get_mapping_for_sensor method."""

    def test_get_mapping_returns_copy(self) -> None:
        """Test that get_mapping_for_sensor returns a copy, not internal reference."""
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

        # Should be equal but different objects
        assert mappings1 == mappings2
        assert mappings1 is not mappings2

    def test_get_mapping_unknown_sensor_returns_empty_list(self) -> None:
        """Test that unknown sensor returns empty list."""
        manifest = create_test_manifest()
        engine = MockFSMEngine()

        router = EventRouter(manifest, engine)

        mappings = router.get_mapping_for_sensor("binary_sensor.nonexistent")

        assert mappings == []
        assert isinstance(mappings, list)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
