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


class DeviceConfig(BaseModel):
    """Device as an actuator inside a room."""

    id: str
    type: str
    name: str = ""
    behaviors: list[BehaviorConfig] = Field(default_factory=list)


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
    """Domain-specific automation rules.

    Поля ночного света объявлены здесь, а не в коде: окно тишины и список
    комнат, где ночью свет включить можно, — это решение владельца дома, а не
    свойство движка. Значения попадают в параметры поведения и читаются
    условием ``may_turn_on``.
    """

    motion_enabled: bool = True
    schedule_enabled: bool = True
    manual_lockout_min: int | None = None
    safety_lockout_enabled: bool = False
    away_mode_enabled: bool = False
    humidity_based: bool = False
    quiet_from: str | None = None
    """С часа ночью движение не включает свет (``HH:MM``)."""
    quiet_to: str | None = None
    """До этого часа включительно — тоже ночь (``HH:MM``)."""
    night_motion_rooms: list[str] | None = None
    """Комнаты, где ночью свет по движению включается (санузел, кухня)."""
    night_off_at: str | None = None
    """Час принудительного выключения света, заданного автоматикой."""
    sleep_modifier: str | None = None
    """Сущность Home Assistant «мы спим» (например, ``input_boolean.sleep_mode``).

    Модификатор включает и выключает владелец сам — автоматизацией HA по
    своему расписанию (например, 23:00–07:00), платформа только читает
    состояние. Пока модификатор включён, яркий свет не включается нигде —
    иначе ночной свет сбивает циркадные ритмы (требование владельца
    2026-10-09). Сущности нет или её состояние неизвестно — модификатора
    нет, и решает солнце/окно тишины, а не «спим»."""
    morning_at: str | None = None
    """Час снятия ночного режима."""
    hold_sec: int | None = None
    """Сколько горит свет после последнего движения."""
    max_on_sec: int | None = None
    """Потолок горения без свежих триггеров."""


class AutomationRules(BaseModel):
    """Global automation rules and domain-specific overrides."""

    global_manual_lockout_min: int = 60
    time_zone: str | None = None
    """Часовой пояс дома. Обязателен для правил «светло ли сейчас»: дом живёт
    в своём поясе, а контейнер — в UTC, и без этого окно дня смещается на
    несколько часов."""
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
