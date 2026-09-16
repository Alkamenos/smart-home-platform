"""Event Router for Smart Home Platform.

Routes sensor events to FSMs via room context.
Same sensor entity can trigger events in multiple rooms.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from .fsm import FSMEngine
from .models.manifest import Manifest


class EventRouter:
    """Routes state change events from sensors to registered FSMs.

    Routing logic:
    - Each room has sensors and devices
    - Sensor event triggers FSMs for ALL devices in that room
    - Same sensor in multiple rooms triggers FSMs in all those rooms
    """

    SENSOR_EVENT_MAP: dict[str, list[str]] = {
        "motion": ["motion_detected", "motion_cleared"],
        "temperature": ["temperature_changed"],
        "humidity": ["humidity_changed"],
        "lux": ["brightness_changed"],
        "contact": ["opened", "closed"],
    }

    def __init__(self, manifest: Manifest, engine: FSMEngine) -> None:
        self._manifest = manifest
        self._engine = engine
        self._sensor_to_fsms: dict[str, list[tuple[str, str]]] = {}
        self._build_mapping()

    def _build_mapping(self) -> None:
        """Build sensor-to-FSM mapping from room structure."""
        for room in self._manifest.rooms:
            # Collect all FSM entity IDs for devices in this room
            room_fsm_ids: list[str] = []
            for device in room.devices:
                room_fsm_ids.extend(self._engine.get_entities_by_device(device.id))

            if not room_fsm_ids:
                continue

            # Each sensor in room routes to all devices in that room
            for sensor_type, sensor_id in room.sensors.items():
                events = self.SENSOR_EVENT_MAP.get(sensor_type, [])
                if not events:
                    logger.warning(f"Unknown sensor type '{sensor_type}' in room '{room.id}'")
                    continue

                for event_name in events:
                    for fsm_id in room_fsm_ids:
                        self._add_mapping(sensor_id, fsm_id, event_name)

        logger.info(f"EventRouter built mapping for {len(self._sensor_to_fsms)} sensors")

    def _add_mapping(self, sensor_id: str, fsm_entity_id: str, event_name: str) -> None:
        """Add a mapping entry."""
        if sensor_id not in self._sensor_to_fsms:
            self._sensor_to_fsms[sensor_id] = []
        entry = (fsm_entity_id, event_name)
        if entry not in self._sensor_to_fsms[sensor_id]:
            self._sensor_to_fsms[sensor_id].append(entry)

    def get_mapping(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor."""
        return list(self._sensor_to_fsms.get(sensor_id, []))

    def get_mapping_for_sensor(self, sensor_id: str) -> list[tuple[str, str]]:
        """Get FSM mappings for a sensor (alias for get_mapping)."""
        return self.get_mapping(sensor_id)

    async def route_state_change(
        self,
        entity_id: str,
        new_state: str,
        old_state: str,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Route a state change event to all registered FSMs."""
        if context is None:
            context = {}

        mappings = self._sensor_to_fsms.get(entity_id, [])
        if not mappings:
            logger.debug(f"No FSM mappings found for sensor {entity_id}")
            return

        for fsm_entity_id, event_name in mappings:
            # Filter events based on state
            if event_name == "motion_detected" and new_state != "on":
                continue
            if event_name == "motion_cleared" and new_state != "off":
                continue

            external_ctx = {
                **context,
                "entity_id": entity_id,
                "new_state": new_state,
                "old_state": old_state,
            }

            logger.info(f"Routing: sensor={entity_id} → fsm={fsm_entity_id}, event={event_name}")

            await self._engine.trigger(
                entity_id=fsm_entity_id,
                event=event_name,
                external_ctx=external_ctx,
            )
