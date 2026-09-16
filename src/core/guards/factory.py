"""Guard factory for creating guards from YAML configuration."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from loguru import logger

from .base import BaseGuard
from .composite_guard import CompositeGuard
from .numeric_guard import NumericGuard
from .state_guard import StateGuard
from .time_guard import TimeGuard


class GuardFactory:
    """Factory for creating guard instances from YAML configuration.

    Usage:
        factory = GuardFactory()
        guard_config = {"type": "time", "between": "23:00-07:00"}
        guard = factory.create(guard_config)
    """

    def create(self, guard_config: dict[str, Any]) -> BaseGuard:
        """Create a guard instance from YAML configuration.

        Args:
            guard_config: Dictionary with guard type and parameters.

        Returns:
            BaseGuard: Created guard instance.

        Raises:
            ValueError: If guard type is unknown or configuration is invalid.
        """
        guard_type = guard_config.get("type")

        if guard_type == "time":
            return self._create_time_guard(guard_config)
        elif guard_type == "state":
            return self._create_state_guard(guard_config)
        elif guard_type == "numeric":
            return self._create_numeric_guard(guard_config)
        elif guard_type in ("and", "or"):
            return self._create_composite_guard(guard_config)
        else:
            raise ValueError(f"Unknown guard type: {guard_type}")

    def _create_time_guard(self, config: dict[str, Any]) -> TimeGuard:
        """Create a time-based guard.

        Args:
            config: Configuration with 'between' field.

        Returns:
            TimeGuard: Created guard instance.
        """
        between = config.get("between")
        if not between:
            raise ValueError("Time guard requires 'between' parameter")
        return TimeGuard(between)

    def _create_state_guard(self, config: dict[str, Any]) -> StateGuard:
        """Create a state-based guard.

        Args:
            config: Configuration with 'entity' and 'is' fields.

        Returns:
            StateGuard: Created guard instance.
        """
        entity = config.get("entity")
        is_state = config.get("is")
        if not entity or not is_state:
            raise ValueError("State guard requires 'entity' and 'is' parameters")
        return StateGuard(entity, is_state)

    def _create_numeric_guard(self, config: dict[str, Any]) -> NumericGuard:
        """Create a numeric comparison guard.

        Args:
            config: Configuration with 'entity', 'operator', and 'value' fields.

        Returns:
            NumericGuard: Created guard instance.
        """
        entity = config.get("entity")
        operator_str = config.get("operator")
        value = config.get("value")
        if not entity or not operator_str or value is None:
            raise ValueError("Numeric guard requires 'entity', 'operator', and 'value' parameters")
        return NumericGuard(entity, operator_str, value)

    def _create_composite_guard(self, config: dict[str, Any]) -> CompositeGuard:
        """Create a composite AND/OR guard.

        Args:
            config: Configuration with 'conditions' list.

        Returns:
            CompositeGuard: Created guard instance.
        """
        conditions = config.get("conditions", [])
        if not conditions:
            logger.warning("Composite guard with no conditions, will always return True")
            return CompositeGuard(config["type"], [])

        child_guards = [self.create(condition) for condition in conditions]
        return CompositeGuard(config["type"], child_guards)
