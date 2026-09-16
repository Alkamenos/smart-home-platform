"""State-based guard for declarative DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from .base import BaseGuard


class StateGuard(BaseGuard):
    """Guard that checks the state of a Home Assistant entity.

    Attributes:
        entity_id: The entity ID to check (e.g., "binary_sensor.alarm").
        expected_state: The expected state value (e.g., "on", "off").
    """

    def __init__(self, entity: str, is_state: str) -> None:
        """Initialize state guard.

        Args:
            entity: The entity ID to check.
            is_state: The expected state value.
        """
        self._entity_id = entity
        self._expected_state = is_state

    def evaluate(self, state: Any, context: dict[str, Any]) -> bool:
        """Check if the entity state matches the expected value.

        Args:
            state: Current FSM state object (unused).
            context: Context dictionary containing entity states.

        Returns:
            bool: True if entity state matches, False otherwise.
        """
        # Context should contain entity states under 'entities' key
        entities = context.get("entities", {})
        current_state = entities.get(self._entity_id, "")
        return current_state == self._expected_state
