"""Tests for Room Aggregation and Policies.

Tests cover:
- Room registration and unregistration
- Sensor state aggregation (occupancy, temperature, humidity, light)
- Policy activation based on schedules
- Different aggregation strategies
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from freezegun import freeze_time
from src.core.models.room import (
    RoomAggregationConfig,
    RoomConfig,
    RoomPolicy,
    RoomPolicyAction,
    RoomState,
)
from src.core.room_manager import RoomManager


class TestRoomModels:
    """Test room model classes."""

    def test_room_aggregation_config_defaults(self) -> None:
        """Test creating room aggregation config with default values."""
        config = RoomAggregationConfig()

        assert config.occupancy == "any_motion"
        assert config.temperature == "average"
        assert config.humidity == "average"
        assert config.light_level == "average"

    def test_room_aggregation_config_custom(self) -> None:
        """Test creating room aggregation config with custom values."""
        config = RoomAggregationConfig(
            occupancy="majority",
            temperature="max",
            humidity="min",
            light_level="average",
        )

        assert config.occupancy == "majority"
        assert config.temperature == "max"
        assert config.humidity == "min"

    def test_room_policy_action_creation(self) -> None:
        """Test creating a room policy action."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})

        assert action.service == "turn_on"
        assert action.data == {"brightness": 10}

    def test_room_policy_creation(self) -> None:
        """Test creating a room policy."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
            enabled=True,
        )

        assert policy.id == "night_mode"
        assert policy.type == "night_mode"
        assert policy.schedule == "23:00-07:00"
        assert policy.enabled is True

    def test_room_config_with_aggregation(self) -> None:
        """Test creating a room config with aggregation settings."""
        aggregation = RoomAggregationConfig(occupancy="any_motion")
        room = RoomConfig(
            id="bedroom",
            name="Bedroom",
            aggregation=aggregation,
            sensor_ids=["binary_sensor.motion"],
            device_ids=["light.bedroom"],
        )

        assert room.id == "bedroom"
        assert room.name == "Bedroom"
        assert room.aggregation.occupancy == "any_motion"
        assert room.sensor_ids == ["binary_sensor.motion"]

    def test_room_config_has_policies_property(self) -> None:
        """Test has_policies property."""
        room_without_policies = RoomConfig(id="room1", name="Room 1")
        assert room_without_policies.has_policies is False

        policy = RoomPolicy(id="policy1", type="test", enabled=True)
        room_with_policies = RoomConfig(id="room2", name="Room 2", policies=[policy])
        assert room_with_policies.has_policies is True

    def test_room_config_active_policies_property(self) -> None:
        """Test active_policies property."""
        policy1 = RoomPolicy(id="policy1", type="test", enabled=True)
        policy2 = RoomPolicy(id="policy2", type="test", enabled=False)
        room = RoomConfig(id="room", name="Room", policies=[policy1, policy2])

        active = room.active_policies
        assert len(active) == 1
        assert active[0].id == "policy1"

    def test_room_state_defaults(self) -> None:
        """Test creating a room state with default values."""
        state = RoomState(room_id="bedroom")

        assert state.room_id == "bedroom"
        assert state.occupancy is False
        assert state.temperature is None
        assert state.humidity is None
        assert state.light_level is None
        assert state.active_policies == []


class TestRoomManager:
    """Test Room Manager functionality."""

    def test_room_manager_initialization(self) -> None:
        """Test initializing Room Manager."""
        manager = RoomManager()

        assert manager._rooms == {}
        assert manager._room_states == {}

    def test_register_room(self) -> None:
        """Test registering a room."""
        manager = RoomManager()
        room = RoomConfig(id="bedroom", name="Bedroom")

        manager.register_room(room)

        assert "bedroom" in manager.list_rooms()
        assert manager.get_room("bedroom") == room

    def test_unregister_room(self) -> None:
        """Test unregistering a room."""
        manager = RoomManager()
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager.register_room(room)

        manager.unregister_room("bedroom")

        assert "bedroom" not in manager.list_rooms()
        assert manager.get_room("bedroom") is None

    def test_get_room_state(self) -> None:
        """Test getting room state."""
        manager = RoomManager()
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager.register_room(room)

        state = manager.get_room_state("bedroom")

        assert state is not None
        assert state.room_id == "bedroom"

    def test_update_motion_sensor_any_motion(self) -> None:
        """Test updating motion sensor with any_motion strategy."""
        aggregation = RoomAggregationConfig(occupancy="any_motion")
        room = RoomConfig(id="bedroom", name="Bedroom", aggregation=aggregation)
        manager = RoomManager()
        manager.register_room(room)

        # Motion detected - should set occupancy to True
        manager.update_sensor_state("bedroom", "motion", "binary_sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.occupancy is True

    def test_update_temperature_average(self) -> None:
        """Test updating temperature with average strategy."""
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "temperature", "sensor.temp", 22.5)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.temperature == 22.5

    def test_update_temperature_min_strategy(self) -> None:
        """Test updating temperature with min strategy."""
        aggregation = RoomAggregationConfig(temperature="min")
        room = RoomConfig(id="bedroom", name="Bedroom", aggregation=aggregation)
        manager = RoomManager()
        manager.register_room(room)

        # First value
        manager.update_sensor_state("bedroom", "temperature", "sensor.temp1", 22.0)
        # Lower value - should update
        manager.update_sensor_state("bedroom", "temperature", "sensor.temp2", 20.0)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.temperature == 20.0

    def test_update_temperature_max_strategy(self) -> None:
        """Test updating temperature with max strategy."""
        aggregation = RoomAggregationConfig(temperature="max")
        room = RoomConfig(id="bedroom", name="Bedroom", aggregation=aggregation)
        manager = RoomManager()
        manager.register_room(room)

        # First value
        manager.update_sensor_state("bedroom", "temperature", "sensor.temp1", 22.0)
        # Higher value - should update
        manager.update_sensor_state("bedroom", "temperature", "sensor.temp2", 25.0)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.temperature == 25.0

    def test_update_humidity(self) -> None:
        """Test updating humidity sensor."""
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "humidity", "sensor.humidity", 65.0)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.humidity == 65.0

    def test_update_light_level(self) -> None:
        """Test updating light level sensor."""
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "light", "sensor.light", 300.0)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.light_level == 300.0

    def test_update_unknown_room(self) -> None:
        """Test updating sensor state for unknown room."""
        manager = RoomManager()

        # Should not raise, just log warning
        manager.update_sensor_state("unknown_room", "motion", "sensor.motion", True)

    def test_get_aggregated_state(self) -> None:
        """Test getting aggregated state dictionary."""
        room = RoomConfig(id="bedroom", name="Bedroom")
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "temperature", "sensor.temp", 22.5)
        manager.update_sensor_state("bedroom", "humidity", "sensor.humidity", 65.0)

        aggregated = manager.get_aggregated_state("bedroom")

        assert aggregated is not None
        assert aggregated["room_id"] == "bedroom"
        assert aggregated["temperature"] == 22.5
        assert aggregated["humidity"] == 65.0

    def test_reload_rooms(self) -> None:
        """Test reloading rooms from new configuration."""
        manager = RoomManager()
        room1 = RoomConfig(id="bedroom", name="Bedroom")
        manager.register_room(room1)

        # Reload with new rooms
        room2 = RoomConfig(id="living_room", name="Living Room")
        manager.reload_rooms([room2])

        assert "bedroom" not in manager.list_rooms()
        assert "living_room" in manager.list_rooms()


class TestRoomPolicies:
    """Test room policy functionality."""

    @freeze_time("2026-09-18 23:30:00")
    def test_policy_active_during_schedule(self) -> None:
        """Test policy is active during its schedule."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        # Trigger an update to check policies
        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert "night_mode" in state.active_policies

    @freeze_time("2026-09-18 14:00:00")
    def test_policy_inactive_outside_schedule(self) -> None:
        """Test policy is inactive outside its schedule."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        # Trigger an update to check policies
        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert "night_mode" not in state.active_policies

    def test_disabled_policy_not_active(self) -> None:
        """Test disabled policy is never active."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
            enabled=False,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        # Trigger an update to check policies
        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert state.active_policies == []

    def test_policy_without_schedule_always_active(self) -> None:
        """Test policy without schedule is always active."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="always_on",
            type="comfort_mode",
            applies_to="all_lights",
            action=action,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        # Trigger an update to check policies
        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert "always_on" in state.active_policies

    @freeze_time("2026-09-18 02:00:00")
    def test_midnight_crossing_schedule_early_morning(self) -> None:
        """Test midnight-crossing schedule works in early morning."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert "night_mode" in state.active_policies

    @freeze_time("2026-09-18 22:59:00")
    def test_midnight_crossing_schedule_before_start(self) -> None:
        """Test midnight-crossing schedule before start time."""
        action = RoomPolicyAction(service="turn_on", data={"brightness": 10})
        policy = RoomPolicy(
            id="night_mode",
            type="night_mode",
            schedule="23:00-07:00",
            applies_to="all_lights",
            action=action,
        )
        room = RoomConfig(id="bedroom", name="Bedroom", policies=[policy])
        manager = RoomManager()
        manager.register_room(room)

        manager.update_sensor_state("bedroom", "motion", "sensor.motion", True)

        state = manager.get_room_state("bedroom")
        assert state is not None
        assert "night_mode" not in state.active_policies
