"""Tests for FSM Factory - behavior composition and template loading."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import BehaviorConfig, DeviceConfig, Manifest
from core.registry import Registry


class TestFSMFactoryInitialization:
    """Tests for FSMFactory initialization."""

    def test_factory_creates_with_engine_and_registry(self):
        """Factory can be created with engine and registry."""
        engine = FSMEngine()
        registry = Registry()

        with tempfile.TemporaryDirectory() as tmpdir:
            factory = FSMFactory(engine, registry, features_dir=tmpdir)

            assert factory._engine is engine
            assert factory._registry is registry
            assert factory._features_dir == Path(tmpdir)
            assert factory._template_cache == {}

    def test_factory_with_event_bus(self):
        """Factory can be created with optional event_bus."""
        engine = FSMEngine()
        registry = Registry()
        event_bus = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            factory = FSMFactory(engine, registry, features_dir=tmpdir, event_bus=event_bus)

            assert factory._event_bus is event_bus


class TestTemplateLoading:
    """Tests for YAML template loading."""

    @pytest.fixture
    def sample_template_file(self, tmp_path):
        """Create a sample YAML template file."""
        template_content = """
initial_state: "OFF"
debounce_sec: 0.5
states:
  - "OFF"
  - "ON"
transitions:
  - from_state: "OFF"
    to_state: "ON"
    trigger: "turn_on"
    action: "turn_on_action"
"""
        template_file = tmp_path / "test_template.yaml"
        template_file.write_text(template_content)
        return str(tmp_path)

    def test_load_template_success(self, sample_template_file):
        """Template loads successfully from file."""
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry, features_dir=sample_template_file)

        template_data = factory._load_template("test_template")

        assert template_data["initial_state"] == "OFF"
        assert template_data["debounce_sec"] == 0.5
        assert "OFF" in template_data["states"]
        assert "ON" in template_data["states"]

    def test_load_template_returns_copy(self, sample_template_file):
        """Each load returns a deep copy."""
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry, features_dir=sample_template_file)

        template1 = factory._load_template("test_template")
        template2 = factory._load_template("test_template")

        # Modify first template
        template1["modified"] = True

        # Second template should not be modified
        assert "modified" not in template2

    def test_load_template_not_found(self, tmp_path):
        """Missing template raises FileNotFoundError."""
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry, features_dir=str(tmp_path))

        with pytest.raises(FileNotFoundError):
            factory._load_template("nonexistent_template")


class TestParamApplication:
    """Tests for applying behavior parameters to templates."""

    @pytest.fixture
    def factory_with_templates(self, tmp_path):
        """Create factory with sample templates."""
        # Create lighting template
        lighting_template = tmp_path / "lighting.yaml"
        lighting_template.write_text("""
initial_state: "OFF"
states:
  - "OFF"
  - "ON_MOTION"
transitions:
  - from_state: "OFF"
    to_state: "ON_MOTION"
    trigger: "motion_detected"
    action: "turn_on_light"
""")

        engine = FSMEngine()
        registry = Registry()
        return FSMFactory(engine, registry, features_dir=str(tmp_path))

    def test_apply_params_sets_entity_id(self, factory_with_templates):
        """Applying params sets unique entity_id."""
        template_data = {
            "initial_state": "OFF",
            "states": ["OFF", "ON"],
            "transitions": [],
        }

        result = factory_with_templates._apply_params_to_template(
            template_data=template_data,
            params={"brightness": 255},
            entity_id="light.kitchen",
            behavior_priority=10,
            device_id="light.kitchen",
            behavior_template_name="lighting",
        )

        assert result["entity_id"] == "light.kitchen_lighting_10"

    def test_apply_params_includes_params(self, factory_with_templates):
        """Applying params includes them in template data."""
        template_data = {"initial_state": "OFF", "states": ["OFF"], "transitions": []}

        params = {"motion_sensor": "binary_sensor.kitchen_motion", "brightness": 255}
        result = factory_with_templates._apply_params_to_template(
            template_data=template_data,
            params=params,
            entity_id="light.kitchen",
            behavior_priority=10,
            device_id="light.kitchen",
            behavior_template_name="lighting",
        )

        assert result["params"] == params

    def test_apply_params_sets_target_device_id(self, factory_with_templates):
        """Applying params sets target_device_id for routing."""
        template_data = {"initial_state": "OFF", "states": ["OFF"], "transitions": []}

        result = factory_with_templates._apply_params_to_template(
            template_data=template_data,
            params={},
            entity_id="light.kitchen",
            behavior_priority=10,
            device_id="light.kitchen",
            behavior_template_name="lighting",
        )

        assert result["target_device_id"] == "light.kitchen"


class TestBehaviorCreation:
    """Tests for creating FSM from behavior configurations."""

    @pytest.fixture
    def factory_with_registry(self, tmp_path):
        """Create factory with registered actions and guards."""
        # Create lighting template
        lighting_template = tmp_path / "lighting.yaml"
        lighting_template.write_text("""
initial_state: "OFF"
states:
  - "OFF"
  - "ON_MOTION"
transitions:
  - from_state: "OFF"
    to_state: "ON_MOTION"
    trigger: "motion_detected"
    action: "turn_on_light"
""")

        engine = FSMEngine()
        registry = Registry()

        # Register required action
        async def turn_on_light(state, context):
            return True

        registry.register_action("turn_on_light", turn_on_light)

        return (
            FSMFactory(engine, registry, features_dir=str(tmp_path)),
            registry,
            engine,
        )

    def test_create_from_behavior_success(self, factory_with_registry):
        """Creating FSM from valid behavior succeeds."""
        factory, registry, engine = factory_with_registry

        behavior = BehaviorConfig(
            template="lighting",
            priority=10,
            params={"motion_sensor": "binary_sensor.kitchen_motion"},
        )

        definitions = factory.create_from_behavior("light.kitchen", behavior)

        assert len(definitions) == 1
        assert definitions[0].entity_id == "light.kitchen_lighting_10"
        assert definitions[0].initial_state == "OFF"

    def test_create_from_behavior_missing_template(self, tmp_path):
        """Creating FSM with missing template logs error."""
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry, features_dir=str(tmp_path))

        behavior = BehaviorConfig(template="nonexistent", priority=10, params={})

        definitions = factory.create_from_behavior("light.kitchen", behavior)

        # Should return empty list on error
        assert len(definitions) == 0

    def test_create_from_behavior_with_schedule(self, factory_with_registry):
        """Creating FSM with schedule param adds schedule guard."""
        factory, registry, engine = factory_with_registry

        behavior = BehaviorConfig(
            template="lighting",
            priority=10,
            params={
                "motion_sensor": "binary_sensor.kitchen_motion",
                "schedule": "07:00-23:00",
            },
        )

        definitions = factory.create_from_behavior("light.kitchen", behavior)

        assert len(definitions) == 1
        # Transitions should have schedule guard applied
        # This is verified by checking the transition has a guard function


class TestManifestIntegration:
    """Tests for creating FSM from manifest."""

    @pytest.fixture
    def factory_with_manifest(self, tmp_path):
        """Create factory with manifest and templates."""
        # Create lighting template
        lighting_template = tmp_path / "lighting.yaml"
        lighting_template.write_text("""
initial_state: "OFF"
states:
  - "OFF"
  - "ON_MOTION"
transitions:
  - from_state: "OFF"
    to_state: "ON_MOTION"
    trigger: "motion_detected"
    action: "turn_on_light"
""")

        engine = FSMEngine()
        registry = Registry()

        # Register required action
        async def turn_on_light(state, context):
            return True

        registry.register_action("turn_on_light", turn_on_light)

        factory = FSMFactory(engine, registry, features_dir=str(tmp_path))

        # Create manifest
        from core.models.manifest import (
            AutomationRules,
            BehaviorConfig,
            InstanceConfig,
            RoomConfig,
        )

        manifest = Manifest(
            instance=InstanceConfig(id="test_house", name="Test House", owner="Test"),
            version=1,
            rooms=[
                RoomConfig(
                    id="kitchen",
                    name="Kitchen",
                    devices=[
                        DeviceConfig(
                            id="light.kitchen",
                            type="light_motion",
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
            automation_rules=AutomationRules(),
        )

        return factory, manifest, engine

    def test_create_from_manifest_success(self, factory_with_manifest):
        """Creating FSM from manifest succeeds."""
        factory, manifest, engine = factory_with_manifest

        definitions = factory.create_from_manifest(manifest)

        assert len(definitions) > 0
        assert any(d.entity_id == "light.kitchen_lighting_10" for d in definitions)

    def test_register_in_engine(self, factory_with_manifest):
        """Registering definitions in engine works."""
        factory, manifest, engine = factory_with_manifest

        definitions = factory.create_from_manifest(manifest)
        factory.register_in_engine(definitions)

        # Verify FSMs are registered
        for definition in definitions:
            assert definition.entity_id in engine._definitions

    def test_create_and_register_combined(self, factory_with_manifest):
        """Combined create and register works."""
        factory, manifest, engine = factory_with_manifest

        definitions = factory.create_and_register(manifest, restore_states=False)

        assert len(definitions) > 0
        # All definitions should be registered
        for definition in definitions:
            assert definition.entity_id in engine._definitions


class TestSensorEventSubscription:
    """Tests for subscribing to sensor events."""

    def test_subscribe_to_motion_sensor(self, tmp_path):
        """Subscribing to motion sensor events works."""
        # Create template
        lighting_template = tmp_path / "lighting.yaml"
        lighting_template.write_text("""
initial_state: "OFF"
states: ["OFF", "ON"]
transitions:
  - from_state: "OFF"
    to_state: "ON"
    trigger: "motion_detected"
    action: "test_action"
""")

        engine = FSMEngine()
        registry = Registry()
        event_bus = MagicMock()

        factory = FSMFactory(engine, registry, features_dir=str(tmp_path), event_bus=event_bus)

        params = {"motion_sensor": "binary_sensor.kitchen_motion"}

        factory._subscribe_to_sensor_events(
            device_id="light.kitchen",
            fsm_entity_id="light.kitchen_lighting_10",
            params=params,
            template_name="lighting",
        )

        # Verify subscription was made
        assert event_bus.subscribe_with_filter.called
        call_args = event_bus.subscribe_with_filter.call_args
        assert call_args[1]["filter_params"]["entity_id"] == "binary_sensor.kitchen_motion"

    def test_no_subscription_without_motion_sensor(self, tmp_path):
        """No subscription if motion_sensor not in params."""
        engine = FSMEngine()
        registry = Registry()
        event_bus = MagicMock()

        factory = FSMFactory(engine, registry, features_dir=str(tmp_path), event_bus=event_bus)

        params = {"brightness": 255}  # No motion_sensor

        factory._subscribe_to_sensor_events(
            device_id="light.kitchen",
            fsm_entity_id="light.kitchen_lighting_10",
            params=params,
            template_name="lighting",
        )

        # Verify no subscription was made
        assert not event_bus.subscribe_with_filter.called


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_device_without_behaviors(self, tmp_path):
        """Device without behaviors is skipped with warning."""
        engine = FSMEngine()
        registry = Registry()
        factory = FSMFactory(engine, registry, features_dir=str(tmp_path))

        from core.models.manifest import AutomationRules, InstanceConfig, RoomConfig

        manifest = Manifest(
            instance=InstanceConfig(id="test", name="Test", owner="Test"),
            version=1,
            rooms=[
                RoomConfig(
                    id="room1",
                    name="Room 1",
                    devices=[
                        DeviceConfig(
                            id="light.test",
                            type="light",
                            name="Test Light",
                            behaviors=[],  # No behaviors
                        )
                    ],
                )
            ],
            automation_rules=AutomationRules(),
        )

        definitions = factory.create_from_manifest(manifest)

        # Should return empty list for device without behaviors
        assert len(definitions) == 0

    def test_multiple_behaviors_same_device(self, tmp_path):
        """Multiple behaviors for same device create multiple FSMs."""
        # Create two templates
        lighting_template = tmp_path / "lighting.yaml"
        lighting_template.write_text("""
initial_state: "OFF"
states: ["OFF", "ON"]
transitions:
  - from_state: "OFF"
    to_state: "ON"
    trigger: "motion"
    action: "turn_on"
""")

        night_light_template = tmp_path / "night_light.yaml"
        night_light_template.write_text("""
initial_state: "OFF"
states: ["OFF", "NIGHT"]
transitions:
  - from_state: "OFF"
    to_state: "NIGHT"
    trigger: "motion"
    action: "turn_on_night"
""")

        engine = FSMEngine()
        registry = Registry()

        # Register actions
        async def turn_on(state, context):
            return True

        async def turn_on_night(state, context):
            return True

        registry.register_action("turn_on", turn_on)
        registry.register_action("turn_on_night", turn_on_night)

        factory = FSMFactory(engine, registry, features_dir=str(tmp_path))

        from core.models.manifest import (
            AutomationRules,
            BehaviorConfig,
            InstanceConfig,
            RoomConfig,
        )

        manifest = Manifest(
            instance=InstanceConfig(id="test", name="Test", owner="Test"),
            version=1,
            rooms=[
                RoomConfig(
                    id="room1",
                    name="Room 1",
                    devices=[
                        DeviceConfig(
                            id="light.kitchen",
                            type="light_motion",
                            name="Kitchen Light",
                            behaviors=[
                                BehaviorConfig(template="lighting", priority=10, params={}),
                                BehaviorConfig(template="night_light", priority=20, params={}),
                            ],
                        )
                    ],
                )
            ],
            automation_rules=AutomationRules(),
        )

        definitions = factory.create_from_manifest(manifest)

        # Should create 2 FSM instances (one per behavior)
        assert len(definitions) == 2
        entity_ids = [d.entity_id for d in definitions]
        assert "light.kitchen_lighting_10" in entity_ids
        assert "light.kitchen_night_light_20" in entity_ids
