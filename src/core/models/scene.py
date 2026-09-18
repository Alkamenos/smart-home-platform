"""Scene models for Smart Home Platform.

Scene Manager allows complex multi-device scenarios:
- Parallel actions (all at once)
- Sequential actions (one after another)
- Triggers (time, button, state changes)
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SceneAction(BaseModel):
    """A single action within a scene.

    Attributes:
        device: Entity ID of the device to control.
        service: Home Assistant service to call (e.g., 'turn_on', 'turn_off').
        data: Optional service data payload.
        delay_sec: Delay before executing this action (for sequential scenes).
    """

    device: str
    service: str
    data: dict[str, Any] = Field(default_factory=dict)
    delay_sec: float = 0.0


class SceneTrigger(BaseModel):
    """Trigger that can activate a scene.

    Attributes:
        type: Trigger type ('time', 'button', 'state').
        at: Time string for time-based triggers (e.g., '19:00').
        entity_id: Entity ID for button/state triggers.
        event: Event type for button triggers (e.g., 'press').
        from_state: Previous state for state triggers.
        to_state: New state for state triggers.
    """

    type: Literal["time", "button", "state"]
    at: str | None = None
    entity_id: str | None = None
    event: str | None = None
    from_state: str | None = None
    to_state: str | None = None


class SceneConfig(BaseModel):
    """Scene configuration.

    A scene is a collection of actions that can be triggered by various events.

    Attributes:
        id: Unique scene identifier.
        name: Human-readable scene name.
        description: Optional scene description.
        actions: List of actions to execute when scene is activated.
        triggers: List of triggers that can activate the scene.
        execution_mode: 'parallel' (all at once) or 'sequential' (with delays).
        enabled: Whether the scene is active.
    """

    id: str
    name: str
    description: str = ""
    actions: list[SceneAction] = Field(default_factory=list)
    triggers: list[SceneTrigger] = Field(default_factory=list)
    execution_mode: Literal["parallel", "sequential"] = "parallel"
    enabled: bool = True

    @property
    def has_sequential_actions(self) -> bool:
        """Check if scene has sequential actions with delays."""
        if self.execution_mode == "sequential":
            return True
        return any(action.delay_sec > 0 for action in self.actions)


class SceneManagerConfig(BaseModel):
    """Configuration for Scene Manager.

    Attributes:
        scenes: List of scene configurations.
        auto_reload: Whether to auto-reload scenes on manifest changes.
    """

    scenes: list[SceneConfig] = Field(default_factory=list)
    auto_reload: bool = True
