"""Room models for Smart Home Platform.

Room Aggregation & Policies allows rooms to:
- Aggregate device states (occupancy, temperature, etc.)
- Apply zone-based policies automatically
- Support different aggregation strategies
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RoomAggregationConfig(BaseModel):
    """Configuration for room state aggregation.

    Attributes:
        occupancy: Strategy for occupancy detection ('any_motion', 'all_motion', 'majority').
        temperature: Strategy for temperature aggregation ('average', 'min', 'max').
        humidity: Strategy for humidity aggregation ('average', 'min', 'max').
        light_level: Strategy for light level aggregation ('average', 'min', 'max').
    """

    occupancy: Literal["any_motion", "all_motion", "majority"] = "any_motion"
    temperature: Literal["average", "min", "max"] = "average"
    humidity: Literal["average", "min", "max"] = "average"
    light_level: Literal["average", "min", "max"] = "average"


class RoomPolicyAction(BaseModel):
    """Action to be applied by a room policy.

    Attributes:
        service: Home Assistant service to call.
        data: Service data payload.
    """

    service: str
    data: dict[str, Any] = Field(default_factory=dict)


class RoomPolicy(BaseModel):
    """Room-level policy configuration.

    Attributes:
        id: Unique policy identifier.
        type: Policy type ('night_mode', 'eco_mode', 'comfort_mode', etc.).
        schedule: Time schedule for policy activation (e.g., '23:00-07:00').
        applies_to: Target devices ('all_lights', 'all_climate', specific entity IDs).
        action: Action to apply when policy is active.
        enabled: Whether the policy is active.
    """

    id: str
    type: str
    schedule: str | None = None
    applies_to: str | list[str] = "all_lights"
    action: RoomPolicyAction | None = None
    enabled: bool = True


class RoomConfig(BaseModel):
    """Extended room configuration with aggregation and policies.

    Attributes:
        id: Unique room identifier.
        name: Human-readable room name.
        aggregation: Aggregation configuration for room sensors.
        policies: List of room-level policies.
        sensor_ids: List of sensor entity IDs in the room.
        device_ids: List of device entity IDs in the room.
    """

    id: str
    name: str
    aggregation: RoomAggregationConfig = Field(default_factory=RoomAggregationConfig)
    policies: list[RoomPolicy] = Field(default_factory=list)
    sensor_ids: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)

    @property
    def has_policies(self) -> bool:
        """Check if room has any enabled policies."""
        return any(policy.enabled for policy in self.policies)

    @property
    def active_policies(self) -> list[RoomPolicy]:
        """Get list of enabled policies."""
        return [policy for policy in self.policies if policy.enabled]


class RoomState(BaseModel):
    """Current aggregated state of a room.

    Attributes:
        room_id: ID of the room.
        occupancy: Whether room is occupied.
        temperature: Aggregated temperature value.
        humidity: Aggregated humidity value.
        light_level: Aggregated light level.
        active_policies: List of currently active policy IDs.
        last_updated: Timestamp of last state update.
    """

    room_id: str
    occupancy: bool = False
    temperature: float | None = None
    humidity: float | None = None
    light_level: float | None = None
    active_policies: list[str] = Field(default_factory=list)
    last_updated: str | None = None
