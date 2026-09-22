"""Manifest models for Smart Home Platform v3.1.

Room-based architecture:
- Rooms contain sensors (inputs) and devices (actuators)
- Sensors describe room state
- Devices react to processed sensor events
- Same sensor entity can be referenced from multiple rooms
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


class InstanceConfig(BaseModel):
    """Platform instance metadata."""

    id: str
    name: str
    owner: str = ""
    created_at: str = ""


class BehaviorConfig(BaseModel):
    """Behavior template with priority and params."""

    template: str
    priority: int = 10
    params: dict[str, Any] = Field(default_factory=dict)


class DeviceCapabilities(BaseModel):
    """Device capabilities based on HA domain and entity features."""

    domain: str = "unknown"  # HA domain: light, switch, climate, etc.
    supported_features: list[str] = Field(default_factory=list)
    unit_of_measurement: str | None = None
    device_class: str | None = None


class DeviceOrigin(BaseModel):
    """Information about where the device was imported from."""

    source: str = "manual"  # manual, home_assistant, mqtt, etc.
    instance_id: str | None = None  # HA instance ID if imported
    imported_at: str | None = None  # ISO timestamp of import
    last_synced_at: str | None = None  # Last successful sync timestamp


class DeviceConfig(BaseModel):
    """Device as an actuator inside a room.

    Extended with origin tracking and external identifiers for idempotent imports.
    """

    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)

    # New fields for Phase 1: Import support
    origin: DeviceOrigin = Field(default_factory=DeviceOrigin)
    external_ids: dict[str, str] = Field(
        default_factory=dict
    )  # {source: external_id}, e.g., {"home_assistant": "light.bedroom_main"}
    capabilities: DeviceCapabilities | None = None  # Optional capabilities info


class RoomConfig(BaseModel):
    """Room: container for sensors and devices.

    Sensors describe room state (inputs).
    Devices are actuators that react to processed events (outputs).
    Same sensor entity_id can appear in multiple rooms.
    """

    id: str
    name: str
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)

    @field_validator("sensors")
    @classmethod
    def validate_sensor_ids(cls, v: dict[str, str]) -> dict[str, str]:
        """Ensure sensor entity IDs are non-empty."""
        for sensor_type, entity_id in v.items():
            if not entity_id.strip():
                raise ValueError(f"Sensor '{sensor_type}' has empty entity_id")
        return v


class AutomationDomainRules(BaseModel):
    """Domain-specific automation rules."""

    motion_enabled: bool = True
    schedule_enabled: bool = True
    manual_lockout_min: int | None = None
    safety_lockout_enabled: bool = False
    away_mode_enabled: bool = False
    humidity_based: bool = False


class AutomationRules(BaseModel):
    """Global automation rules and domain-specific overrides."""

    global_manual_lockout_min: int = 60
    lighting: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    climate: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    ventilation: AutomationDomainRules = Field(default_factory=AutomationDomainRules)


class Dashboard(BaseModel):
    """Dashboard configuration for Lovelace generation."""

    title: str = ""
    rooms: list[str] = Field(default_factory=list)
    show_sensors: bool = True
    show_devices: bool = True


class Manifest(BaseModel):
    """Root manifest model for room-based architecture."""

    instance: InstanceConfig
    version: int = 1
    rooms: list[RoomConfig] = Field(default_factory=list)
    automation_rules: AutomationRules = Field(default_factory=AutomationRules)
    dashboard: Dashboard = Field(default_factory=Dashboard)

    @property
    def devices(self) -> list[DeviceConfig]:
        """Flat list of all devices across all rooms."""
        return [device for room in self.rooms for device in room.devices]

    @property
    def zones(self) -> list[RoomConfig]:
        """Alias for rooms (backward compat with old Zone model)."""
        return self.rooms

    @property
    def all_devices(self) -> list[tuple[str, DeviceConfig]]:
        """Flat list of (room_id, device) for iteration."""
        return [(room.id, device) for room in self.rooms for device in room.devices]

    @property
    def all_device_ids(self) -> list[str]:
        """Flat list of all device IDs."""
        return [device.id for _, device in self.all_devices]

    def get_room_for_device(self, device_id: str) -> RoomConfig | None:
        """Find the room containing a device."""
        for room in self.rooms:
            if any(d.id == device_id for d in room.devices):
                return room
        return None

    def get_device(self, device_id: str) -> DeviceConfig | None:
        """Find a device by ID across all rooms."""
        for _, device in self.all_devices:
            if device.id == device_id:
                return device
        return None

    def get_sensors_for_device(self, device_id: str) -> dict[str, str]:
        """Get sensors available for a device (from its room)."""
        room = self.get_room_for_device(device_id)
        return room.sensors if room else {}

    def find_device_by_external_id(
        self, origin_source: str, external_id: str
    ) -> tuple[RoomConfig, DeviceConfig] | None:
        """
        Find a device by external ID and origin source.

        Args:
            origin_source: Origin source (e.g., 'home_assistant')
            external_id: External ID from the source system

        Returns:
            Tuple of (RoomConfig, DeviceConfig) if found, None otherwise
        """
        for room in self.rooms:
            for device in room.devices:
                if (
                    device.origin
                    and device.origin.source == origin_source
                    and device.external_ids
                    and device.external_ids.get(origin_source) == external_id
                ):
                    return (room, device)
        return None

    def add_or_update_device(
        self,
        room_id: str,
        device: DeviceConfig,
    ) -> tuple[bool, DeviceConfig]:
        """
        Add new device or update existing one in a room.

        Args:
            room_id: ID of the room to add/update device in
            device: DeviceConfig to add or update

        Returns:
            Tuple of (is_new, device) where is_new is True if device was created
        """
        # Find room
        room = next((r for r in self.rooms if r.id == room_id), None)
        if not room:
            raise ValueError(f"Room {room_id} not found")

        # Check if device exists by external_id
        if device.external_ids:
            for origin_source, ext_id in device.external_ids.items():
                existing = self.find_device_by_external_id(origin_source, ext_id)
                if existing:
                    existing_room, existing_device = existing
                    # Update existing device
                    existing_device.name = device.name
                    existing_device.capabilities = device.capabilities
                    existing_device.origin.last_synced_at = device.origin.last_synced_at
                    return (False, existing_device)

        # Check if device exists by ID
        existing_device = next((d for d in room.devices if d.id == device.id), None)
        if existing_device:
            # Update existing device
            existing_device.name = device.name
            existing_device.type = device.type
            existing_device.behaviors = device.behaviors
            existing_device.origin = device.origin
            existing_device.external_ids = device.external_ids
            existing_device.capabilities = device.capabilities
            return (False, existing_device)

        # Add new device
        room.devices.append(device)
        return (True, device)


# ─── Backward compatibility aliases ───────────────────────────────────────────
# Старые имена для совместимости с существующими тестами и модулями

ClimateAutomation = AutomationDomainRules
LightingAutomation = AutomationDomainRules
VentilationAutomation = AutomationDomainRules
AnyDevice = DeviceConfig
LightMotionDevice = DeviceConfig


# ─── Loader function (kept here for import compatibility) ─────────────────────


def load_manifest(manifest_path: str | Path) -> Manifest:
    """Load and validate manifest from YAML file.

    Args:
        manifest_path: Path to manifest YAML file.

    Returns:
        Validated Manifest instance.

    Raises:
        FileNotFoundError: If manifest file doesn't exist.
        pydantic.ValidationError: If manifest is invalid.
    """
    path = Path(manifest_path)
    if not path.exists():
        raise FileNotFoundError(f"Manifest not found: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return Manifest.model_validate(data)


# Zone в новой архитектуре = Room
class Zone(BaseModel):
    """Zone is now an alias for RoomConfig with optional floor."""

    id: str
    name: str
    floor: int = 1
    sensors: dict[str, str] = Field(default_factory=dict)
    devices: list[DeviceConfig] = Field(default_factory=list)


InstanceInfo = InstanceConfig
