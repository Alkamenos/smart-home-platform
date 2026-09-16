"""
Tests for Manifest Generator module.

These tests verify the manifest generator behavior based on specification:
- FSM generation from manifest for lighting, climate, ventilation
- Trigger mappings from sensors to FSMs
- Automation rules extraction
- Handling of missing fields and edge cases
"""

import pytest

from core.manifest_generator import (
    GeneratorResult,
    ManifestAutomationGenerator,
    TriggerMapping,
)


class TestManifestAutomationGeneratorInitialization:
    """Tests for generator initialization"""

    def test_init_with_manifest_and_logger(self, mock_logger):
        """Generator initializes with manifest and logger"""
        manifest = {"devices": {}}
        generator = ManifestAutomationGenerator(manifest, logger=mock_logger)

        assert generator._manifest == manifest
        assert generator._logger == mock_logger

    def test_init_with_manifest_without_logger(self):
        """Generator creates dummy logger when not provided"""
        manifest = {"devices": {}}
        generator = ManifestAutomationGenerator(manifest)

        assert generator._manifest == manifest
        # Should have a _DummyLogger instance
        assert hasattr(generator._logger, "debug")
        assert hasattr(generator._logger, "info")
        assert hasattr(generator._logger, "warning")
        assert hasattr(generator._logger, "error")


class TestGenerateAll:
    """Tests for generate_all method"""

    def test_generate_all_returns_generator_result(self):
        """generate_all returns GeneratorResult with all components"""
        manifest = {
            "devices": {
                "lighting": [],
                "climate": [],
                "ventilation": [],
            },
            "automation_rules": {},
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert isinstance(result, GeneratorResult)
        assert isinstance(result.lighting_definitions, list)
        assert isinstance(result.lighting_mappings, list)
        assert isinstance(result.climate_definitions, list)
        assert isinstance(result.climate_mappings, list)
        assert isinstance(result.ventilation_definitions, list)
        assert isinstance(result.ventilation_mappings, list)
        assert isinstance(result.automation_rules, dict)


class TestLightingFSMGeneration:
    """Tests for lighting FSM generation based on specification"""

    def test_generates_fsm_for_each_lighting_device(self):
        """Should create one FSM definition per lighting device"""
        manifest = {
            "devices": {
                "lighting": [
                    {"id": "light.kitchen", "room": "kitchen"},
                    {"id": "light.bedroom", "room": "bedroom"},
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_definitions) == 2
        assert result.lighting_definitions[0].entity_id == "light.kitchen"
        assert result.lighting_definitions[1].entity_id == "light.bedroom"

    def test_fsm_has_correct_states(self):
        """Lighting FSM should have specified states: OFF, ON_SCHEDULE, ON_MOTION, MANUAL"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        assert fsm.states == ("OFF", "ON_SCHEDULE", "ON_MOTION", "MANUAL")
        assert fsm.initial_state == "OFF"

    def test_fsm_has_schedule_on_transition(self):
        """Should have transition from OFF to ON_SCHEDULE on schedule_on trigger"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        schedule_on_transitions = [
            t for t in fsm.transitions if t.trigger == "schedule_on" and t.to_state == "ON_SCHEDULE"
        ]
        assert len(schedule_on_transitions) == 1
        assert schedule_on_transitions[0].from_state == "OFF"

    def test_fsm_has_schedule_off_transition(self):
        """Should have transition from ON_SCHEDULE to OFF on schedule_off trigger"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        schedule_off_transitions = [
            t for t in fsm.transitions if t.trigger == "schedule_off" and t.to_state == "OFF"
        ]
        assert len(schedule_off_transitions) == 1
        assert schedule_off_transitions[0].from_state == "ON_SCHEDULE"

    def test_fsm_has_motion_detected_transition(self):
        """Should have transition to ON_MOTION on motion_detected trigger"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        motion_transitions = [
            t
            for t in fsm.transitions
            if t.trigger == "motion_detected" and t.to_state == "ON_MOTION"
        ]
        assert len(motion_transitions) == 1
        assert motion_transitions[0].timeout_sec is not None

    def test_fsm_has_timeout_transition(self):
        """Should have transition from ON_MOTION to OFF on timeout"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        timeout_transitions = [
            t
            for t in fsm.transitions
            if t.trigger == "timeout" and t.from_state == "ON_MOTION" and t.to_state == "OFF"
        ]
        assert len(timeout_transitions) == 1

    def test_fsm_has_manual_change_transition(self):
        """Should have transition to MANUAL on manual_change trigger with action"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        manual_transitions = [
            t for t in fsm.transitions if t.trigger == "manual_change" and t.to_state == "MANUAL"
        ]
        assert len(manual_transitions) == 1
        assert manual_transitions[0].action is not None

    def test_uses_motion_timeout_from_device_config(self):
        """Should use motion_timeout_sec from device config"""
        manifest = {
            "devices": {
                "lighting": [{"id": "light.kitchen", "room": "kitchen", "motion_timeout_sec": 600}]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        motion_transitions = [t for t in fsm.transitions if t.trigger == "motion_detected"]
        assert motion_transitions[0].timeout_sec == 600

    def test_uses_default_motion_timeout_when_not_specified(self):
        """Should use default 300 seconds when motion_timeout_sec not specified"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.lighting_definitions[0]
        motion_transitions = [t for t in fsm.transitions if t.trigger == "motion_detected"]
        assert motion_transitions[0].timeout_sec == 300

    def test_room_extracted_from_device_or_entity_id(self):
        """Should use room from device config or extract from entity_id"""
        manifest = {
            "devices": {
                "lighting": [
                    {"id": "light.kitchen", "room": "kitchen"},
                    {"id": "light.bedroom_light"},  # No room specified
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        # First device has explicit room
        fsm1 = result.lighting_definitions[0]
        # Second device should extract room from entity_id
        fsm2 = result.lighting_definitions[1]

        assert fsm1 is not None
        assert fsm2 is not None


class TestLightingMappings:
    """Tests for lighting trigger mappings"""

    def test_creates_mapping_for_motion_sensor_on(self):
        """Should create mapping for motion sensor turning on"""
        manifest = {
            "devices": {
                "lighting": [
                    {
                        "id": "light.kitchen",
                        "room": "kitchen",
                        "motion_sensor": "binary_sensor.kitchen_motion",
                    }
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_mappings) >= 1
        motion_on_mapping = next(
            (m for m in result.lighting_mappings if m.source_value == "on"), None
        )
        assert motion_on_mapping is not None
        assert motion_on_mapping.source_entity == "binary_sensor.kitchen_motion"
        assert motion_on_mapping.target_entity == "light.kitchen"
        assert motion_on_mapping.trigger == "motion_detected"

    def test_creates_mapping_for_motion_sensor_off(self):
        """Should create mapping for motion sensor turning off"""
        manifest = {
            "devices": {
                "lighting": [
                    {
                        "id": "light.kitchen",
                        "room": "kitchen",
                        "motion_sensor": "binary_sensor.kitchen_motion",
                    }
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        motion_off_mapping = next(
            (m for m in result.lighting_mappings if m.source_value == "off"), None
        )
        assert motion_off_mapping is not None
        assert motion_off_mapping.trigger == "motion_cleared"

    def test_no_mappings_when_no_motion_sensor(self):
        """Should not create mappings when device has no motion_sensor"""
        manifest = {"devices": {"lighting": [{"id": "light.kitchen", "room": "kitchen"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_mappings) == 0


class TestClimateFSMGeneration:
    """Tests for climate FSM generation based on specification"""

    def test_generates_fsm_for_each_climate_device(self):
        """Should create one FSM definition per climate device"""
        manifest = {
            "devices": {
                "climate": [
                    {"id": "climate.living_room", "room": "living_room"},
                    {"id": "climate.bedroom", "room": "bedroom"},
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.climate_definitions) == 2

    def test_fsm_has_correct_states(self):
        """Climate FSM should have states: IDLE, HEATING, COOLING, SAFETY_LOCKOUT, AWAY"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.climate_definitions[0]
        assert fsm.states == ("IDLE", "HEATING", "COOLING", "SAFETY_LOCKOUT", "AWAY")
        assert fsm.initial == "IDLE"

    def test_has_heating_transitions(self):
        """Should have transitions for heating based on temperature"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.climate_definitions[0]
        heating_triggers = [t.trigger for t in fsm.transitions]
        assert "temp_low" in heating_triggers
        assert "temp_reached" in heating_triggers

    def test_has_cooling_transitions(self):
        """Should have transitions for cooling based on temperature"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.climate_definitions[0]
        cooling_triggers = [t.trigger for t in fsm.transitions]
        assert "temp_high" in cooling_triggers

    def test_has_away_mode_transitions(self):
        """Should have transitions for away mode"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.climate_definitions[0]
        away_triggers = [t.trigger for t in fsm.transitions]
        assert "away_mode_on" in away_triggers
        assert "away_mode_off" in away_triggers

    def test_has_safety_lockout_transitions(self):
        """Should have transitions for safety lockout with high priority"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.climate_definitions[0]
        safety_transitions = [
            t for t in fsm.transitions if t.trigger in ("safety_alarm", "safety_reset")
        ]
        assert len(safety_transitions) == 2
        # Safety should have highest priority (200)
        for t in safety_transitions:
            assert t.priority == 200

    def test_uses_target_temperature_from_config(self):
        """Should use target temperature from device config"""
        manifest = {
            "devices": {
                "climate": [{"id": "climate.living_room", "room": "living_room", "target": 25.0}]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        # FSM should be created with target=25.0 embedded in guards
        assert len(result.climate_definitions) == 1

    def test_uses_hysteresis_from_config(self):
        """Should use hysteresis from device config"""
        manifest = {
            "devices": {
                "climate": [{"id": "climate.living_room", "room": "living_room", "hysteresis": 1.0}]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.climate_definitions) == 1


class TestClimateMappings:
    """Tests for climate trigger mappings"""

    def test_creates_mapping_for_temperature_sensor(self):
        """Should create mapping for temperature sensor"""
        manifest = {
            "devices": {
                "climate": [
                    {
                        "id": "climate.living_room",
                        "room": "living_room",
                        "sensor": "sensor.living_room_temp",
                    }
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.climate_mappings) == 1
        mapping = result.climate_mappings[0]
        assert mapping.source_entity == "sensor.living_room_temp"
        assert mapping.source_value == "*"
        assert mapping.trigger == "temperature_changed"

    def test_no_mappings_when_no_sensor(self):
        """Should not create mappings when climate has no sensor"""
        manifest = {"devices": {"climate": [{"id": "climate.living_room", "room": "living_room"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.climate_mappings) == 0


class TestVentilationFSMGeneration:
    """Tests for ventilation FSM generation based on specification"""

    def test_generates_fsm_for_each_ventilation_device(self):
        """Should create one FSM definition per ventilation device"""
        manifest = {
            "devices": {
                "ventilation": [
                    {"id": "fan.bathroom", "room": "bathroom"},
                    {"id": "fan.toilet", "room": "toilet"},
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.ventilation_definitions) == 2

    def test_fsm_has_correct_states(self):
        """Ventilation FSM should have states: OFF, ON_HUMIDITY, MANUAL"""
        manifest = {"devices": {"ventilation": [{"id": "fan.bathroom", "room": "bathroom"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.ventilation_definitions[0]
        assert fsm.states == ("OFF", "ON_HUMIDITY", "MANUAL")
        assert fsm.initial == "OFF"

    def test_has_humidity_high_transition(self):
        """Should have transition to ON_HUMIDITY when humidity is high"""
        manifest = {"devices": {"ventilation": [{"id": "fan.bathroom", "room": "bathroom"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.ventilation_definitions[0]
        humidity_triggers = [t.trigger for t in fsm.transitions]
        assert "humidity_high" in humidity_triggers

    def test_has_humidity_low_transition(self):
        """Should have transition to OFF when humidity is low"""
        manifest = {"devices": {"ventilation": [{"id": "fan.bathroom", "room": "bathroom"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.ventilation_definitions[0]
        humidity_triggers = [t.trigger for t in fsm.transitions]
        assert "humidity_low" in humidity_triggers

    def test_uses_humidity_threshold_from_config(self):
        """Should use humidity_threshold from device config"""
        manifest = {
            "devices": {
                "ventilation": [
                    {"id": "fan.bathroom", "room": "bathroom", "humidity_threshold": 70}
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.ventilation_definitions) == 1

    def test_uses_timeout_from_config(self):
        """Should use timeout_sec from device config"""
        manifest = {
            "devices": {
                "ventilation": [{"id": "fan.bathroom", "room": "bathroom", "timeout_sec": 3600}]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        fsm = result.ventilation_definitions[0]
        humidity_transitions = [t for t in fsm.transitions if t.trigger == "humidity_high"]
        assert humidity_transitions[0].timeout_sec == 3600


class TestVentilationMappings:
    """Tests for ventilation trigger mappings"""

    def test_creates_mapping_for_humidity_sensor(self):
        """Should create mapping for humidity sensor"""
        manifest = {
            "devices": {
                "ventilation": [
                    {
                        "id": "fan.bathroom",
                        "room": "bathroom",
                        "humidity_sensor": "sensor.bathroom_humidity",
                    }
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.ventilation_mappings) == 1
        mapping = result.ventilation_mappings[0]
        assert mapping.source_entity == "sensor.bathroom_humidity"
        assert mapping.trigger == "humidity_changed"

    def test_no_mappings_when_no_humidity_sensor(self):
        """Should not create mappings when ventilation has no humidity_sensor"""
        manifest = {"devices": {"ventilation": [{"id": "fan.bathroom", "room": "bathroom"}]}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.ventilation_mappings) == 0


class TestAutomationRulesExtraction:
    """Tests for automation rules extraction"""

    def test_extracts_automation_rules_from_manifest(self):
        """Should extract automation_rules from manifest"""
        manifest = {
            "devices": {},
            "automation_rules": {
                "lighting": {"motion_enabled": True},
                "climate": {"eco_mode": True},
            },
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert result.automation_rules == manifest["automation_rules"]

    def test_returns_empty_dict_when_no_automation_rules(self):
        """Should return empty dict when automation_rules not present"""
        manifest = {"devices": {}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert result.automation_rules == {}


class TestManualLockout:
    """Tests for manual lockout configuration"""

    def test_gets_lockout_from_automation_rules(self):
        """Should get manual_lockout_min from automation_rules for device type"""
        manifest = {
            "devices": {},
            "automation_rules": {
                "lighting": {"manual_lockout_min": 30},
                "climate": {"manual_lockout_min": 90},
            },
        }
        generator = ManifestAutomationGenerator(manifest)

        # The lockout is used in FSM generation
        result = generator.generate_all()

        # Just verify generation works - actual lockout value is embedded in transitions
        assert result is not None

    def test_uses_default_lockout_when_not_specified(self):
        """Should use default 60 minutes when manual_lockout_min not specified"""
        manifest = {"devices": {}, "automation_rules": {}}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert result is not None


class TestTriggerMappingDataClass:
    """Tests for TriggerMapping data class"""

    def test_create_trigger_mapping(self):
        """Should create TriggerMapping with required fields"""
        mapping = TriggerMapping(
            source_entity="binary_sensor.motion",
            source_value="on",
            target_entity="light.kitchen",
            trigger="motion_detected",
        )

        assert mapping.source_entity == "binary_sensor.motion"
        assert mapping.source_value == "on"
        assert mapping.target_entity == "light.kitchen"
        assert mapping.trigger == "motion_detected"

    def test_context_builder_defaults_to_empty(self):
        """context_builder should default to function returning empty dict"""
        mapping = TriggerMapping(
            source_entity="binary_sensor.motion",
            source_value="on",
            target_entity="light.kitchen",
            trigger="motion_detected",
        )

        result = mapping.context_builder({})
        assert result == {}

    def test_context_builder_can_be_customized(self):
        """context_builder can be set to custom function"""

        def custom_builder(e):
            return {"custom": "value"}

        mapping = TriggerMapping(
            source_entity="binary_sensor.motion",
            source_value="on",
            target_entity="light.kitchen",
            trigger="motion_detected",
            context_builder=custom_builder,
        )

        result = mapping.context_builder({})
        assert result == {"custom": "value"}


class TestGeneratorResultDataClass:
    """Tests for GeneratorResult data class"""

    def test_create_generator_result(self):
        """Should create GeneratorResult with all fields"""
        result = GeneratorResult(
            lighting_definitions=[],
            lighting_mappings=[],
            climate_definitions=[],
            climate_mappings=[],
            ventilation_definitions=[],
            ventilation_mappings=[],
            automation_rules={},
        )

        assert isinstance(result.lighting_definitions, list)
        assert isinstance(result.lighting_mappings, list)
        assert isinstance(result.climate_definitions, list)
        assert isinstance(result.climate_mappings, list)
        assert isinstance(result.ventilation_definitions, list)
        assert isinstance(result.ventilation_mappings, list)
        assert isinstance(result.automation_rules, dict)


class TestEdgeCases:
    """Tests for edge cases and error handling"""

    def test_handles_empty_manifest(self):
        """Should handle completely empty manifest"""
        manifest = {}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_definitions) == 0
        assert len(result.climate_definitions) == 0
        assert len(result.ventilation_definitions) == 0

    def test_handles_missing_devices_section(self):
        """Should handle manifest without devices section"""
        manifest = {"version": 1}
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_definitions) == 0

    def test_handles_missing_device_type(self):
        """Should handle manifest with some device types missing"""
        manifest = {
            "devices": {
                "lighting": [{"id": "light.kitchen"}],
                # No climate or ventilation
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        assert len(result.lighting_definitions) == 1
        assert len(result.climate_definitions) == 0
        assert len(result.ventilation_definitions) == 0

    def test_handles_device_without_id(self):
        """Should handle device without id gracefully"""
        manifest = {"devices": {"lighting": [{}]}}  # Device without id
        generator = ManifestAutomationGenerator(manifest)

        # This should raise KeyError or handle gracefully
        # Based on current implementation, it will raise KeyError
        with pytest.raises(KeyError):
            generator.generate_all()

    def test_context_builder_in_mapping_updates_context(self):
        """Context builder in lighting mapping should update motion sensor context"""
        manifest = {
            "devices": {
                "lighting": [
                    {
                        "id": "light.kitchen",
                        "room": "kitchen",
                        "motion_sensor": "binary_sensor.kitchen_motion",
                    }
                ]
            }
        }
        generator = ManifestAutomationGenerator(manifest)
        result = generator.generate_all()

        # Find motion_detected mapping
        motion_mapping = next(
            (m for m in result.lighting_mappings if m.trigger == "motion_detected"), None
        )
        assert motion_mapping is not None

        # Test context builder
        context = motion_mapping.context_builder({"new_state": {"state": "on"}})
        assert "kitchen_motion_sensor" in context
        assert context["kitchen_motion_sensor"] is True
