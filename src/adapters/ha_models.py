"""Home Assistant data models for device import.

This module defines data structures for representing Home Assistant
registry information (areas, devices, entities) in a typed manner.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AreaInfo:
    """Home Assistant Area information.

    Areas represent physical locations/zones in a home.

    Attributes:
        id: Unique area identifier (e.g., "bedroom", "kitchen")
        name: Human-readable area name
        floor_id: Optional floor identifier if floors are used
        labels: List of user-defined labels for categorization
    """

    id: str
    name: str
    floor_id: str | None = None
    labels: list[str] = field(default_factory=list)


@dataclass
class DeviceInfo:
    """Home Assistant Device information.

    Devices represent physical hardware that may have multiple entities.

    Attributes:
        id: Unique device identifier in HA registry
        name: Human-readable device name
        model: Device model number/name
        manufacturer: Device manufacturer
        sw_version: Software/firmware version
        hw_version: Hardware version
        serial_number: Device serial number
        identifiers: List of (domain, id) tuples for external identification
        connections: List of (connection_type, value) tuples (e.g., MAC address)
        area_id: ID of the area this device belongs to
        labels: User-defined labels
        created_at: When the device was added to HA
    """

    id: str
    name: str
    model: str | None = None
    manufacturer: str | None = None
    sw_version: str | None = None
    hw_version: str | None = None
    serial_number: str | None = None
    identifiers: list[tuple[str, str]] = field(default_factory=list)
    connections: list[tuple[str, str]] = field(default_factory=list)
    area_id: str | None = None
    labels: list[str] = field(default_factory=list)
    created_at: datetime | None = None


@dataclass
class EntityInfo:
    """Home Assistant Entity information.

    Entities are the basic building blocks - sensors, actuators, etc.
    Each entity belongs to exactly one domain (light, switch, sensor, etc.)

    Attributes:
        entity_id: Full entity ID (e.g., "light.bedroom_main")
        name: Human-readable entity name (may be None)
        platform: Integration platform (e.g., "hue", "zwave")
        domain: Entity domain (e.g., "light", "binary_sensor")
        device_id: ID of parent device (if any)
        area_id: ID of area (inherited from device or set directly)
        labels: User-defined labels
        disabled_by: Why entity is disabled ('user', 'integration', 'config_entry')
        hidden_by: Why entity is hidden ('user', 'integration')
        capabilities: Entity capabilities (e.g., supported features)
        device_class: Standard device class for the domain
        unit_of_measurement: Unit for numeric entities
        state: Current state value
        attributes: Additional entity attributes
    """

    entity_id: str
    name: str | None = None
    platform: str = ""
    domain: str = ""
    device_id: str | None = None
    area_id: str | None = None
    labels: list[str] = field(default_factory=list)
    disabled_by: str | None = None
    hidden_by: str | None = None
    capabilities: dict[str, Any] = field(default_factory=dict)
    device_class: str | None = None
    unit_of_measurement: str | None = None
    state: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class EntityState:
    """Current state of a Home Assistant entity.

    Represents a point-in-time snapshot of an entity's state.

    Attributes:
        entity_id: Full entity ID
        state: Current state value (string representation)
        attributes: State attributes (dict)
        last_changed: When the state last changed
        last_updated: When the state was last updated (may differ from changed)
        context: Context information (user_id, parent_id, etc.)
    """

    entity_id: str
    state: str
    attributes: dict[str, Any]
    last_changed: datetime
    last_updated: datetime
    context: dict[str, Any] = field(default_factory=dict)
