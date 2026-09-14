"""
Event Router for Smart Home Platform.

This module provides event routing from sensors to FSMs based on manifest configuration.
It maps sensor events to FSM triggers, enabling decoupled communication between
sensor devices and automation behaviors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from .fsm import FSMEngine
from .models.manifest import LightMotionDevice, Manifest


@dataclass
class SensorMapping:
    """Represents a mapping from a sensor to FSM events."""

    sensor_id: str
    fsm_entity_id: str
    event_name: str


class EventRouter:
    """
    Routes state change events from sensors to registered FSMs.

    The EventRouter builds a mapping between sensor entity IDs and FSMs that should
    respond to their events. This mapping is derived from the manifest's device
    configurations and behavior parameters.

    Attributes:
        manifest: The smart home manifest containing device definitions.
        engine: The FSM engine that will receive trigger calls.
        _sensor_to_fsms: Internal mapping from sensor_id to list of (fsm_entity_id, event_name) tuples.
    """

    def __init__(self, manifest: Manifest, engine: FSMEngine) -> None:
        """
        Initialize the EventRouter with a manifest and FSM engine.

        Args:
            manifest: The smart home manifest containing device and behavior definitions.
            engine: The FSM engine instance to trigger events on.
        """
        self._manifest = manifest
        self._engine = engine
        self._sensor_to_fsms: dict[str, list[tuple[str, str]]] = {}
        self._build_mapping()

    def _build_mapping(self) -> None:
        """
        Build the sensor-to-FSM mapping from the manifest.

        Iterates through all devices in the manifest and extracts sensor mappings
        from behavior parameters. Also handles special cases for light_motion devices.

        Mapping rules:
        - motion_sensor -> motion_detected (on) / motion_cleared (off)
        - humidity_sensor -> humidity_changed
        - sensor (temperature) -> temperature_changed
        - light_motion device type -> manual_switch_on/off for the device itself
        """
        for device in self._manifest.devices:
            # Get all registered FSM entity_ids for this device
            # FSM entity_ids follow pattern: {device_id}_{template}_{priority}
            fsm_entity_ids = self._get_fsm_entity_ids_for_device(device.id)

            for behavior in device.behaviors:
                params = behavior.params
                template = behavior.template
                priority = behavior.priority

                # Build FSM entity_id
                fsm_entity_id = f"{device.id}_{template}_{priority}"

                # Check for motion_sensor in params
                if "motion_sensor" in params:
                    sensor_id = params["motion_sensor"]
                    self._add_mapping(sensor_id, fsm_entity_id, "motion_detected")
                    self._add_mapping(sensor_id, fsm_entity_id, "motion_cleared")

                # Check for humidity_sensor in params
                if "humidity_sensor" in params:
                    sensor_id = params["humidity_sensor"]
                    self._add_mapping(sensor_id, fsm_entity_id, "humidity_changed")

                # Check for sensor (temperature) in params
                if "sensor" in params:
                    sensor_id = params["sensor"]
                    self._add_mapping(sensor_id, fsm_entity_id, "temperature_changed")

            # Special handling for light_motion device type
            # Map the device itself to manual switch events
            if (
                isinstance(device, LightMotionDevice)
                or getattr(device, "type", None) == "light_motion"
            ):
                device_id = device.id
                # For each FSM associated with this device, add manual switch mappings
                for fsm_entity_id in fsm_entity_ids:
                    self._add_mapping(device_id, fsm_entity_id, "manual_switch_on")
                    self._add_mapping(device_id, fsm_entity_id, "manual_switch_off")

        logger.info(f"EventRouter built mapping for {len(self._sensor_to_fsms)} sensors")

    def _get_fsm_entity_ids_for_device(self, device_id: str) -> list[str]:
        """
        Get all FSM entity IDs registered for a given device.

        Args:
            device_id: The device ID to look up.

        Returns:
            List of FSM entity IDs that belong to this device.
        """
        fsm_ids = []
        for registered_id in self._engine._definitions:
            if registered_id.startswith(f"{device_id}_"):
                fsm_ids.append(registered_id)
        return fsm_ids

    def _add_mapping(self, sensor_id: str, fsm_entity_id: str, event_name: str) -> None:
        """
        Add a mapping entry from sensor to FSM.

        Args:
            sensor_id: The sensor entity ID.
            fsm_entity_id: The FSM entity ID to trigger.
            event_name: The event name to trigger on the FSM.
        """
        if sensor_id not in self._sensor_to_fsms:
            self._sensor_to_fsms[sensor_id] = []

        entry = (fsm_entity_id, event_name)
        if entry not in self._sensor_to_fsms[sensor_id]:
            self._sensor_to_fsms[sensor_id].append(entry)

    async def route_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """
        Route a state change event to all registered FSMs.

        Looks up the entity_id in the sensor-to-FSM mapping and triggers
        appropriate events on each matching FSM. Only triggers motion_detected
        when new_state is "on", and motion_cleared when new_state is "off".

        Args:
            entity_id: The entity ID that changed state (e.g., binary_sensor.kitchen_motion).
            new_state: The new state value (e.g., "on", "off").
            old_state: The previous state value.
            context: Optional context dictionary to pass to the FSM trigger.
        """
        if context is None:
            context = {}

        mappings = self._sensor_to_fsms.get(entity_id, [])

        if not mappings:
            logger.debug(f"No FSM mappings found for sensor {entity_id}")
            return

        for fsm_entity_id, event_name in mappings:
            # Filter events based on state for motion sensors
            if event_name == "motion_detected" and new_state != "on":
                logger.debug(f"Skipping motion_detected for {entity_id}: new_state={new_state}")
                continue

            if event_name == "motion_cleared" and new_state != "off":
                logger.debug(f"Skipping motion_cleared for {entity_id}: new_state={new_state}")
                continue

            # Trigger the FSM with the event
            external_ctx = {
                **context,
                "entity_id": entity_id,
                "new_state": new_state,
                "old_state": old_state,
            }

            logger.info(
                f"Routing event: sensor={entity_id} -> fsm={fsm_entity_id}, "
                f"event={event_name}, new_state={new_state}"
            )

            await self._engine.trigger(
                entity_id=fsm_entity_id,
                event=event_name,
                external_ctx=external_ctx,
            )

    def get_mapping_for_sensor(self, sensor_id: str) -> list[tuple[str, str]]:
        """
        Get the FSM mappings for a specific sensor.

        Useful for debugging and testing to verify the routing configuration.

        Args:
            sensor_id: The sensor entity ID to look up.

        Returns:
            List of (fsm_entity_id, event_name) tuples for the sensor.
            Returns empty list if sensor is not mapped.
        """
        return list(self._sensor_to_fsms.get(sensor_id, []))
