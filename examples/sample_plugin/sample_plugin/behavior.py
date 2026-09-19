"""Sample behavior plugin for Smart Home Platform.

This is an example plugin that adds a "Party Mode" behavior to the system.
It demonstrates how to create a plugin that can be discovered and loaded
automatically by the platform.

To use this plugin:

1. Install it as a package (or link in development mode):
   pip install -e examples/sample_plugin

2. The plugin will be automatically discovered on next platform start.

3. The Party Mode behavior will be available for use in FSM definitions.
"""

from typing import Any


class PartyModeBehavior:
    """Party Mode behavior plugin.

    This plugin adds a party mode automation that:
    - Enables colorful lighting scenes
    - Adjusts music volume based on noise level
    - Manages access control during parties

    Example registration in pyproject.toml::

        [project.entry-points."smart_home.behaviors"]
        party_mode = "sample_plugin.behavior:PartyModeBehavior"
    """

    name = "party_mode"
    description = "Adds party mode automation with dynamic lighting and sound control"
    version = "1.0.0"

    def get_fsm_definition(self) -> dict[str, Any]:
        """Return FSM definition for party mode behavior.

        Returns:
            FSM definition with states and transitions for party mode.
        """
        return {
            "states": {
                "idle": {
                    "description": "Waiting for party to start",
                },
                "active": {
                    "description": "Party mode is active",
                },
                "winding_down": {
                    "description": "Party is ending, gradual shutdown",
                },
            },
            "transitions": [
                {
                    "from": "idle",
                    "to": "active",
                    "trigger": "party_started",
                    "guards": ["time_is_evening"],
                },
                {
                    "from": "active",
                    "to": "winding_down",
                    "trigger": "party_ending",
                    "guards": ["time_is_late"],
                },
                {
                    "from": "winding_down",
                    "to": "idle",
                    "trigger": "party_finished",
                    "guards": ["all_guests_left"],
                },
            ],
            "initial_state": "idle",
        }

    def get_guards(self) -> dict[str, Any]:
        """Return guard functions for party mode.

        Returns:
            Dictionary of guard name to function mappings.
        """
        from datetime import datetime

        def time_is_evening(context: dict[str, Any]) -> bool:
            """Check if current time is evening (6 PM - 10 PM)."""
            hour = datetime.now().hour
            return 18 <= hour < 22

        def time_is_late(context: dict[str, Any]) -> bool:
            """Check if current time is late (after 10 PM)."""
            hour = datetime.now().hour
            return hour >= 22 or hour < 6

        def all_guests_left(context: dict[str, Any]) -> bool:
            """Check if all guests have left (mock implementation)."""
            # In real implementation, check motion sensors, door sensors, etc.
            motion_detected = context.get("motion_detected", False)
            return not motion_detected

        return {
            "time_is_evening": time_is_evening,
            "time_is_late": time_is_late,
            "all_guests_left": all_guests_left,
        }

    def get_actions(self) -> dict[str, Any]:
        """Return action functions for party mode.

        Returns:
            Dictionary of action name to function mappings.
        """

        def enable_party_lights(context: dict[str, Any]) -> None:
            """Enable colorful party lighting."""
            print("[PartyMode] Enabling party lights!")
            # In real implementation: call lighting API

        def disable_party_lights(context: dict[str, Any]) -> None:
            """Disable party lighting and restore normal mode."""
            print("[PartyMode] Disabling party lights.")
            # In real implementation: call lighting API

        def adjust_music_volume(context: dict[str, Any]) -> None:
            """Adjust music volume based on noise level."""
            noise_level = context.get("noise_level", 0)
            print(f"[PartyMode] Adjusting music volume. Noise level: {noise_level}")
            # In real implementation: call audio API

        return {
            "enable_party_lights": enable_party_lights,
            "disable_party_lights": disable_party_lights,
            "adjust_music_volume": adjust_music_volume,
        }
