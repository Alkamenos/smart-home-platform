"""Pydantic models for Web UI form validation.

These models mirror the manifest structure and provide
validation for web form inputs.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BehaviorModel(BaseModel):
    """Behavior configuration model."""

    template: str = Field(..., description="FSM template name")
    priority: int = Field(default=10, ge=1, le=100, description="Behavior priority")
    params: dict[str, Any] = Field(default_factory=dict, description="Template-specific parameters")


class DeviceModel(BaseModel):
    """Device configuration model."""

    type: str = Field(..., description="Device type (e.g., light_motion)")
    id: str = Field(..., description="Entity ID (e.g., light.kitchen)")
    behaviors: list[BehaviorModel] = Field(
        default_factory=list, description="List of behaviors for this device"
    )


class RoomModel(BaseModel):
    """Room configuration model."""

    name: str = Field(..., description="Room name")
    id: str = Field(..., description="Room entity ID")
    devices: list[DeviceModel] = Field(default_factory=list, description="Devices in this room")
    sensors: dict[str, str] = Field(
        default_factory=dict, description="Sensor mappings for this room"
    )


class ManifestModel(BaseModel):
    """Main manifest configuration model."""

    version: str = Field(default="3.0", description="Manifest schema version")
    instance_name: str = Field(..., description="Instance name")
    rooms: list[RoomModel] = Field(default_factory=list, description="Rooms in the smart home")
    global_params: dict[str, Any] = Field(default_factory=dict, description="Global parameters")

    model_config = {"extra": "allow"}
