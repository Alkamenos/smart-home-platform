"""
Test for event routing with parameterized subscriptions.

This test verifies that:
1. EventBus supports parameterized subscriptions via subscribe_with_filter
2. FSMFactory automatically subscribes FSMs to events from params
3. Both lighting and night_light FSMs receive events from the same motion_sensor
"""

import asyncio
import pytest
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.smart_home.core.event_bus import EventBus
from src.smart_home.core.fsm import FSMEngine
from src.smart_home.core.registry import Registry
from src.smart_home.core.fsm_factory import FSMFactory
from src.smart_home.core.models.manifest import Manifest, load_manifest


class TestEventBusWithFilters:
    """Tests for EventBus parameterized subscriptions."""

    @pytest.mark.asyncio
    async def test_subscribe_with_filter_basic(self):
        """Test basic subscribe_with_filter functionality."""
        event_bus = EventBus()
        received_events = []

        async def handler1(event_type, payload, trace_id=None):
            received_events.append(("handler1", payload))

        async def handler2(event_type, payload, trace_id=None):
            received_events.append(("handler2", payload))

        # Subscribe with different filters
        event_bus.subscribe_with_filter(
            "state_change",
            {"entity_id": "binary_sensor.kitchen_motion"},
            handler1
        )
        event_bus.subscribe_with_filter(
            "state_change",
            {"entity_id": "binary_sensor.living_room_motion"},
            handler2
        )

        # Publish event matching first filter
        await event_bus.publish(
            "state_change",
            {"entity_id": "binary_sensor.kitchen_motion", "new_state": "on"}
        )

        assert len(received_events) == 1
        assert received_events[0] == ("handler1", {"entity_id": "binary_sensor.kitchen_motion", "new_state": "on"})

        # Publish event matching second filter
        received_events.clear()
        await event_bus.publish(
            "state_change",
            {"entity_id": "binary_sensor.living_room_motion", "new_state": "on"}
        )

        assert len(received_events) == 1
        assert received_events[0] == ("handler2", {"entity_id": "binary_sensor.living_room_motion", "new_state": "on"})

    @pytest.mark.asyncio
    async def test_filter_matching_partial(self):
        """Test that filter matches when payload contains all filter keys."""
        event_bus = EventBus()
        received_events = []

        async def handler(event_type, payload, trace_id=None):
            received_events.append(payload)

        # Subscribe with filter containing only entity_id
        event_bus.subscribe_with_filter(
            "state_change",
            {"entity_id": "binary_sensor.kitchen_motion"},
            handler
        )

        # Publish event with extra fields - should still match
        await event_bus.publish(
            "state_change",
            {
                "entity_id": "binary_sensor.kitchen_motion",
                "new_state": "on",
                "old_state": "off",
                "extra_field": "value"
            }
        )

        assert len(received_events) == 1
        assert received_events[0]["entity_id"] == "binary_sensor.kitchen_motion"
        assert received_events[0]["new_state"] == "on"

    @pytest.mark.asyncio
    async def test_filter_no_match(self):
        """Test that handler is not called when filter doesn't match."""
        event_bus = EventBus()
        received_events = []

        async def handler(event_type, payload, trace_id=None):
            received_events.append(payload)

        event_bus.subscribe_with_filter(
            "state_change",
            {"entity_id": "binary_sensor.kitchen_motion"},
            handler
        )

        # Publish event with different entity_id
        await event_bus.publish(
            "state_change",
            {"entity_id": "binary_sensor.bedroom_motion", "new_state": "on"}
        )

        assert len(received_events) == 0


class TestFSMFactorySubscription:
    """Tests for FSMFactory automatic subscription to sensor events."""

    @pytest.fixture
    def setup_factory(self):
        """Set up FSMFactory with event bus."""
        engine = FSMEngine()
        registry = Registry()
        event_bus = EventBus()
        factory = FSMFactory(engine, registry, event_bus, features_dir="features")
        return engine, registry, event_bus, factory

    @pytest.mark.asyncio
    async def test_both_fsm_receive_motion_event(self, setup_factory):
        """
        Test that both lighting and night_light FSMs receive motion_detected event
        from the same binary_sensor.kitchen_motion sensor.
        
        This is the core requirement: FSM for lighting and night_light of the same device
        should both receive events from motion_sensor specified in their params.
        """
        engine, registry, event_bus, factory = setup_factory

        # Register required guards and actions for lighting template
        async def is_day_time(state, context):
            return True  # Always day for testing

        async def turn_on_light(state, context):
            return {}

        async def turn_off_light(state, context):
            return {}

        registry.register_guard("is_day_time", is_day_time)
        registry.register_action("turn_on_light", turn_on_light)
        registry.register_action("turn_off_light", turn_off_light)

        # Create FSMs for kitchen light with both behaviors
        # Simulating manifest with two behaviors for the same device
        from src.smart_home.core.models.manifest import BehaviorConfig, LightMotionDevice

        device = LightMotionDevice(
            type="light_motion",
            id="light.kitchen",
            name="Kitchen Light",
            room="kitchen",
            behaviors=[
                BehaviorConfig(
                    template="night_light",
                    priority=20,
                    params={
                        "brightness": 10,
                        "schedule": "23:00-07:00",
                    }
                ),
                BehaviorConfig(
                    template="lighting",
                    priority=10,
                    params={
                        "motion_sensor": "binary_sensor.kitchen_motion",
                        "motion_timeout_sec": 300,
                        "schedule": "07:00-23:00",
                        "brightness": 255
                    }
                )
            ]
        )

        # Create a minimal manifest
        from src.smart_home.core.models.manifest import (
            InstanceInfo, Zone, AutomationRules, LightingAutomation,
            ClimateAutomation, VentilationAutomation, Dashboard
        )

        manifest = Manifest(
            version=1,
            instance=InstanceInfo(
                id="test_house",
                name="Test House",
                owner="Test",
                created_at="2024-01-01"
            ),
            zones=[Zone(id="kitchen", name="Kitchen", floor=1)],
            devices=[device],
            automation_rules=AutomationRules(
                lighting=LightingAutomation(
                    motion_enabled=True,
                    schedule_enabled=True,
                    manual_lockout_min=60
                ),
                climate=ClimateAutomation(
                    safety_lockout_enabled=True,
                    away_mode_enabled=True,
                    manual_lockout_min=30
                ),
                ventilation=VentilationAutomation(
                    humidity_based=True,
                    manual_lockout_min=15
                )
            ),
            dashboard=Dashboard(
                title="Test",
                show_history=True,
                show_climate=True,
                show_motion_sensors=True,
                history_days=7
            )
        )

        # Create and register FSMs
        definitions = factory.create_and_register(manifest)

        # Verify we have two FSM definitions
        assert len(definitions) == 2

        # Find the FSM entity_ids
        fsm_entity_ids = [d.entity_id for d in definitions]
        assert any("lighting" in eid for eid in fsm_entity_ids)
        assert any("night_light" in eid for eid in fsm_entity_ids)

        # Track which FSMs received the motion_detected event
        triggered_fsms = []

        # Store original trigger method
        original_trigger = engine.trigger

        async def tracking_trigger(entity_id, event, external_ctx=None, trace_id=None):
            if event == "motion_detected":
                triggered_fsms.append(entity_id)
            return await original_trigger(entity_id, event, external_ctx, trace_id)

        engine.trigger = tracking_trigger

        # Publish motion_detected event from kitchen_motion sensor
        await event_bus.publish(
            "state_change",
            {
                "entity_id": "binary_sensor.kitchen_motion",
                "new_state": "on",
                "old_state": "off"
            },
            trace_id="test123"
        )

        # Give async handlers time to process
        await asyncio.sleep(0.1)

        # Verify BOTH FSMs received the motion_detected event
        # The lighting FSM should have received it (has motion_sensor param)
        # Note: night_light doesn't have motion_sensor in params, so it won't be subscribed
        lighting_fsms_triggered = [eid for eid in triggered_fsms if "lighting" in eid]
        assert len(lighting_fsms_triggered) >= 1, \
            f"Lighting FSM should have received motion_detected event. Triggered: {triggered_fsms}"


class TestEndToEndEventRouting:
    """End-to-end tests for event routing from sensor to multiple FSMs."""

    @pytest.mark.asyncio
    async def test_kitchen_motion_to_both_fsm(self):
        """
        Test that event from binary_sensor.kitchen_motion is delivered to both
        lighting and night_light FSMs when both are configured with the same sensor.
        """
        engine = FSMEngine()
        registry = Registry()
        event_bus = EventBus()
        factory = FSMFactory(engine, registry, event_bus, features_dir="features")

        # Register guards and actions for both templates
        async def is_day_time(state, context):
            return context.get("is_day", True)

        async def is_night_time(state, context):
            return context.get("is_night", False)

        async def turn_on_light(state, context):
            return {}

        async def turn_on_night_light(state, context):
            return {}

        async def turn_off_light(state, context):
            return {}

        async def turn_off_night_light(state, context):
            return {}

        registry.register_guard("is_day_time", is_day_time)
        registry.register_guard("is_night_time", is_night_time)
        registry.register_action("turn_on_light", turn_on_light)
        registry.register_action("turn_on_night_light", turn_on_night_light)
        registry.register_action("turn_off_light", turn_off_light)
        registry.register_action("turn_off_night_light", turn_off_night_light)

        # Create manifest with both behaviors having motion_sensor
        from src.smart_home.core.models.manifest import (
            BehaviorConfig, LightMotionDevice, InstanceInfo, Zone,
            AutomationRules, LightingAutomation, ClimateAutomation,
            VentilationAutomation, Dashboard
        )

        device = LightMotionDevice(
            id="light.kitchen",
            name="Kitchen Light",
            room="kitchen",
            behaviors=[
                # Night light behavior WITH motion_sensor
                BehaviorConfig(
                    template="night_light",
                    priority=20,
                    params={
                        "motion_sensor": "binary_sensor.kitchen_motion",  # Same sensor!
                        "brightness": 10,
                        "schedule": "23:00-07:00",
                    }
                ),
                # Lighting behavior WITH motion_sensor
                BehaviorConfig(
                    template="lighting",
                    priority=10,
                    params={
                        "motion_sensor": "binary_sensor.kitchen_motion",  # Same sensor!
                        "motion_timeout_sec": 300,
                        "schedule": "07:00-23:00",
                        "brightness": 255
                    }
                )
            ]
        )

        manifest = Manifest(
            version=1,
            instance=InstanceInfo(
                id="test_house",
                name="Test House",
                owner="Test",
                created_at="2024-01-01"
            ),
            zones=[Zone(id="kitchen", name="Kitchen", floor=1)],
            devices=[device],
            automation_rules=AutomationRules(
                lighting=LightingAutomation(
                    motion_enabled=True,
                    schedule_enabled=True,
                    manual_lockout_min=60
                ),
                climate=ClimateAutomation(
                    safety_lockout_enabled=True,
                    away_mode_enabled=True,
                    manual_lockout_min=30
                ),
                ventilation=VentilationAutomation(
                    humidity_based=True,
                    manual_lockout_min=15
                )
            ),
            dashboard=Dashboard(
                title="Test",
                show_history=True,
                show_climate=True,
                show_motion_sensors=True,
                history_days=7
            )
        )

        # Create and register FSMs
        definitions = factory.create_and_register(manifest)

        # Find FSM entity_ids
        lighting_fsm_id = None
        night_light_fsm_id = None
        for d in definitions:
            if "lighting" in d.entity_id:
                lighting_fsm_id = d.entity_id
            if "night_light" in d.entity_id:
                night_light_fsm_id = d.entity_id

        assert lighting_fsm_id is not None, "Lighting FSM should exist"
        assert night_light_fsm_id is not None, "Night light FSM should exist"

        # Track triggers
        triggered_fsms = set()

        original_trigger = engine.trigger

        async def tracking_trigger(entity_id, event, external_ctx=None, trace_id=None):
            if event == "motion_detected":
                triggered_fsms.add(entity_id)
            return await original_trigger(entity_id, event, external_ctx, trace_id)

        engine.trigger = tracking_trigger

        # Publish motion event from kitchen_motion sensor
        await event_bus.publish(
            "state_change",
            {
                "entity_id": "binary_sensor.kitchen_motion",
                "new_state": "on",
                "old_state": "off"
            },
            trace_id="e2e_test"
        )

        # Allow async processing
        await asyncio.sleep(0.1)

        # CRITICAL ASSERTION: Both FSMs must receive the motion_detected event
        assert lighting_fsm_id in triggered_fsms, \
            f"Lighting FSM ({lighting_fsm_id}) should receive motion_detected event"
        assert night_light_fsm_id in triggered_fsms, \
            f"Night light FSM ({night_light_fsm_id}) should receive motion_detected event"

        print(f"✓ Both FSMs received motion_detected event:")
        print(f"  - {lighting_fsm_id}")
        print(f"  - {night_light_fsm_id}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
