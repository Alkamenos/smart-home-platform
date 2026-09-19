"""Room Manager for Smart Home Platform.

Manages room-level aggregation and policies:
- Aggregates sensor states (occupancy, temperature, humidity, light)
- Applies zone-based policies automatically
- Integrates with EventRouter for event-driven updates
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.models.room import RoomConfig, RoomState


if TYPE_CHECKING:
    from ..event_bus import EventBus


class RoomManager:
    """Manages room aggregation and policies.

    The Room Manager is responsible for:
    - Aggregating sensor states within rooms
    - Applying room-level policies based on schedules and conditions
    - Providing room state information to other components

    Attributes:
        event_bus: Event bus for subscribing to sensor events.
        _rooms: Dictionary mapping room IDs to configurations.
        _room_states: Dictionary mapping room IDs to current states.
    """

    def __init__(self, event_bus: EventBus | None = None) -> None:
        """Initialize Room Manager.

        Args:
            event_bus: Optional event bus for sensor event subscriptions.
        """
        self.event_bus = event_bus
        self._rooms: dict[str, RoomConfig] = {}
        self._room_states: dict[str, RoomState] = {}

        logger.info("Room Manager initialized")

    def register_room(self, room_config: RoomConfig) -> None:
        """Register a room with the manager.

        Args:
            room_config: Room configuration to register.
        """
        self._rooms[room_config.id] = room_config
        self._room_states[room_config.id] = RoomState(room_id=room_config.id)

        logger.info(f"Registered room: {room_config.id} ({room_config.name})")

        # Subscribe to sensor events if event bus is available
        if self.event_bus:
            self._subscribe_to_sensors(room_config)

    def unregister_room(self, room_id: str) -> None:
        """Unregister a room.

        Args:
            room_id: ID of the room to unregister.
        """
        if room_id in self._rooms:
            del self._rooms[room_id]
            if room_id in self._room_states:
                del self._room_states[room_id]
            logger.info(f"Unregistered room: {room_id}")

    def get_room(self, room_id: str) -> RoomConfig | None:
        """Get room configuration by ID.

        Args:
            room_id: ID of the room to retrieve.

        Returns:
            Room configuration if found, None otherwise.
        """
        return self._rooms.get(room_id)

    def get_room_state(self, room_id: str) -> RoomState | None:
        """Get current room state by ID.

        Args:
            room_id: ID of the room to retrieve state for.

        Returns:
            Room state if found, None otherwise.
        """
        return self._room_states.get(room_id)

    def list_rooms(self) -> list[str]:
        """List all registered room IDs.

        Returns:
            List of room IDs.
        """
        return list(self._rooms.keys())

    def update_sensor_state(
        self, room_id: str, sensor_type: str, entity_id: str, value: Any
    ) -> None:
        """Update sensor state and recalculate room aggregation.

        Args:
            room_id: ID of the room containing the sensor.
            sensor_type: Type of sensor ('motion', 'temperature', 'humidity', 'light').
            entity_id: Entity ID of the sensor.
            value: New sensor value.
        """
        room = self.get_room(room_id)
        if not room:
            logger.warning(f"Cannot update sensor state: room not found: {room_id}")
            return

        state = self._room_states.get(room_id)
        if not state:
            logger.warning(f"Cannot update sensor state: no state for room: {room_id}")
            return

        # Update aggregated values based on sensor type
        if sensor_type == "motion":
            self._update_occupancy(room_id, entity_id, value)
        elif sensor_type == "temperature":
            self._update_temperature(room_id, value)
        elif sensor_type == "humidity":
            self._update_humidity(room_id, value)
        elif sensor_type == "light":
            self._update_light_level(room_id, value)

        # Update timestamp
        state.last_updated = datetime.now().isoformat()

        # Check and apply policies
        self._check_policies(room_id)

    def _update_occupancy(self, room_id: str, entity_id: str, is_motion: bool) -> None:
        """Update occupancy state based on motion sensor.

        Args:
            room_id: ID of the room.
            entity_id: Entity ID of the motion sensor.
            is_motion: Whether motion was detected.
        """
        room = self._rooms.get(room_id)
        state = self._room_states.get(room_id)
        if not room or not state:
            return

        strategy = room.aggregation.occupancy

        if strategy == "any_motion":
            # Any motion means occupied
            if is_motion:
                state.occupancy = True
        elif strategy == "all_motion":
            # All sensors must detect motion (not implemented for single sensor)
            state.occupancy = is_motion
        elif strategy == "majority":
            # Majority of sensors (simplified for now)
            state.occupancy = is_motion

        logger.debug(f"Room {room_id} occupancy updated: {state.occupancy}")

    def _update_temperature(self, room_id: str, value: float) -> None:
        """Update aggregated temperature.

        Args:
            room_id: ID of the room.
            value: Temperature value.
        """
        state = self._room_states.get(room_id)
        room = self._rooms.get(room_id)
        if not state or not room:
            return

        strategy = room.aggregation.temperature

        if strategy == "average":
            # Simple average (would need multiple sensors in production)
            state.temperature = value
        elif (
            strategy == "min"
            and (state.temperature is None or value < state.temperature)
            or strategy == "max"
            and (state.temperature is None or value > state.temperature)
        ):
            state.temperature = value

        logger.debug(f"Room {room_id} temperature updated: {state.temperature}")

    def _update_humidity(self, room_id: str, value: float) -> None:
        """Update aggregated humidity.

        Args:
            room_id: ID of the room.
            value: Humidity value.
        """
        state = self._room_states.get(room_id)
        room = self._rooms.get(room_id)
        if not state or not room:
            return

        strategy = room.aggregation.humidity

        if (
            strategy == "average"
            or strategy == "min"
            and (state.humidity is None or value < state.humidity)
            or strategy == "max"
            and (state.humidity is None or value > state.humidity)
        ):
            state.humidity = value

        logger.debug(f"Room {room_id} humidity updated: {state.humidity}")

    def _update_light_level(self, room_id: str, value: float) -> None:
        """Update aggregated light level.

        Args:
            room_id: ID of the room.
            value: Light level value.
        """
        state = self._room_states.get(room_id)
        room = self._rooms.get(room_id)
        if not state or not room:
            return

        strategy = room.aggregation.light_level

        if (
            strategy == "average"
            or strategy == "min"
            and (state.light_level is None or value < state.light_level)
            or strategy == "max"
            and (state.light_level is None or value > state.light_level)
        ):
            state.light_level = value

        logger.debug(f"Room {room_id} light level updated: {state.light_level}")

    def _check_policies(self, room_id: str) -> None:
        """Check and apply room policies.

        Args:
            room_id: ID of the room to check policies for.
        """
        room = self._rooms.get(room_id)
        state = self._room_states.get(room_id)
        if not room or not state:
            return

        active_policies: list[str] = []

        for policy in room.active_policies:
            # Check if policy should be active based on schedule
            if self._is_policy_active(policy):
                active_policies.append(policy.id)
                # Apply policy action
                self._apply_policy(room_id, policy)

        state.active_policies = active_policies

        if active_policies:
            logger.debug(f"Room {room_id} active policies: {active_policies}")

    def _is_policy_active(self, policy: Any) -> bool:
        """Check if a policy should be active based on its schedule.

        Args:
            policy: Policy configuration.

        Returns:
            True if policy should be active, False otherwise.
        """
        if not policy.schedule:
            # No schedule means always active
            return True

        # Parse schedule (format: "HH:MM-HH:MM")
        try:
            start_str, end_str = policy.schedule.split("-")
            start_hour, start_min = map(int, start_str.split(":"))
            end_hour, end_min = map(int, end_str.split(":"))

            now = datetime.now()
            current_minutes = now.hour * 60 + now.minute
            start_minutes = start_hour * 60 + start_min
            end_minutes = end_hour * 60 + end_min

            # Handle midnight-crossing schedules
            if start_minutes <= end_minutes:
                return start_minutes <= current_minutes < end_minutes
            else:
                # Schedule crosses midnight (e.g., 23:00-07:00)
                return current_minutes >= start_minutes or current_minutes < end_minutes

        except (ValueError, AttributeError):
            logger.warning(f"Invalid policy schedule: {policy.schedule}")
            return False

    def _apply_policy(self, room_id: str, policy: Any) -> None:
        """Apply a policy action to the room.

        Args:
            room_id: ID of the room.
            policy: Policy configuration with action.
        """
        if not policy.action:
            return

        # TODO: Integrate with actual device control layer
        # For now, just log the policy application
        logger.info(f"Applying policy '{policy.id}' to room {room_id}")
        logger.debug(f"Policy action: {policy.action.service} on {policy.applies_to}")

        # In production, this would call the device control layer
        # Example: await adapter.call_service(policy.action.service, targets, policy.action.data)

    def _subscribe_to_sensors(self, room_config: RoomConfig) -> None:
        """Subscribe to sensor events for a room.

        Args:
            room_config: Room configuration with sensor IDs.
        """
        if not self.event_bus:
            return

        # Subscribe to state change events for room sensors
        for _sensor_id in room_config.sensor_ids:
            # TODO: Implement actual event subscription
            # self.event_bus.subscribe("ha.state_changed", handler)
            pass

    def get_aggregated_state(self, room_id: str) -> dict[str, Any] | None:
        """Get aggregated state for a room.

        Args:
            room_id: ID of the room.

        Returns:
            Dictionary with aggregated state values, or None if room not found.
        """
        state = self._room_states.get(room_id)
        if not state:
            return None

        return {
            "room_id": state.room_id,
            "occupancy": state.occupancy,
            "temperature": state.temperature,
            "humidity": state.humidity,
            "light_level": state.light_level,
            "active_policies": state.active_policies,
            "last_updated": state.last_updated,
        }

    def reload_rooms(self, rooms: list[RoomConfig]) -> None:
        """Reload all rooms from new configuration.

        Args:
            rooms: List of new room configurations.
        """
        logger.info("Reloading rooms from new configuration")

        # Clear existing rooms
        self._rooms.clear()
        self._room_states.clear()

        # Register new rooms
        for room_config in rooms:
            self.register_room(room_config)

        logger.info(f"Reloaded {len(self._rooms)} rooms")
