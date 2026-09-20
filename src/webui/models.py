"""Pydantic models for Smart Home Manifest that match the real structure."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class InstanceConfig(BaseModel):
    """Instance configuration model."""

    id: str = Field(..., description="Unique instance identifier")
    name: str = Field(..., description="Human-readable instance name")
    owner: str = Field(default="Unknown", description="Instance owner")
    created_at: str = Field(default="", description="Creation timestamp")


class BehaviorConfig(BaseModel):
    """Behavior configuration for a device."""

    template: str = Field(..., description="Template name")
    priority: int = Field(..., description="Priority level")
    params: dict[str, Any] = Field(default_factory=dict, description="Behavior parameters")


class DeviceConfig(BaseModel):
    """Device configuration within a room."""

    id: str = Field(..., description="Device entity ID")
    type: str = Field(..., description="Device type")
    name: str = Field(default="", description="Human-readable device name")
    behaviors: list[BehaviorConfig] = Field(default_factory=list, description="Device behaviors")


class RoomConfig(BaseModel):
    """Room configuration model."""

    id: str = Field(..., description="Room identifier")
    name: str = Field(..., description="Human-readable room name")
    sensors: dict[str, str] = Field(default_factory=dict, description="Room sensors")
    devices: list[DeviceConfig] = Field(default_factory=list, description="Room devices")


class AutomationDomainRules(BaseModel):
    """Automation rules for a specific domain."""

    motion_enabled: bool = Field(default=True, description="Enable motion-based automation")
    schedule_enabled: bool = Field(default=True, description="Enable schedule-based automation")
    manual_lockout_min: int = Field(
        default=60, description="Minutes to block automation after manual control"
    )
    safety_lockout_enabled: bool = Field(default=False, description="Enable safety lockout")
    away_mode_enabled: bool = Field(default=False, description="Enable away mode")
    humidity_based: bool = Field(default=False, description="Enable humidity-based automation")


class AutomationRules(BaseModel):
    """Global automation rules."""

    global_manual_lockout_min: int = Field(default=60, description="Global manual lockout minutes")
    lighting: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    climate: AutomationDomainRules = Field(default_factory=AutomationDomainRules)
    ventilation: AutomationDomainRules = Field(default_factory=AutomationDomainRules)


class DashboardConfig(BaseModel):
    """Dashboard configuration."""

    title: str = Field(default="", description="Dashboard title")
    rooms: list[str] = Field(default_factory=list, description="Rooms to show on dashboard")
    show_sensors: bool = Field(default=True, description="Show sensors on dashboard")
    show_devices: bool = Field(default=True, description="Show devices on dashboard")


class ManifestModel(BaseModel):
    """Main manifest configuration model matching real YAML structure."""

    instance: InstanceConfig = Field(..., description="Instance configuration")
    version: int = Field(default=1, description="Manifest schema version")
    rooms: list[RoomConfig] = Field(default_factory=list, description="Rooms in the smart home")
    automation_rules: AutomationRules = Field(
        default_factory=AutomationRules, description="Automation rules"
    )
    dashboard: DashboardConfig = Field(
        default_factory=DashboardConfig, description="Dashboard configuration"
    )

    model_config = {"extra": "allow"}
