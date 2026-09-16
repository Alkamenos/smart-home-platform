"""Numeric comparison guard for declarative DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import operator
from collections.abc import Callable
from typing import Any

from .base import BaseGuard


class NumericGuard(BaseGuard):
    """Guard that performs numeric comparison on a sensor value.

    Attributes:
        entity_id: The sensor entity ID to check.
        operator_str: Comparison operator ("<", ">", "<=", ">=", "==").
        threshold: The numeric threshold value.
    """

    OPERATORS: dict[str, Callable[[float, float], bool]] = {
        "<": operator.lt,
        ">": operator.gt,
        "<=": operator.le,
        ">=": operator.ge,
        "==": operator.eq,
    }

    def __init__(self, entity: str, operator_str: str, value: float) -> None:
        """Initialize numeric guard.

        Args:
            entity: The sensor entity ID.
            operator_str: Comparison operator string.
            value: The threshold value.

        Raises:
            ValueError: If operator is not supported.
        """
        self._entity_id = entity
        if operator_str not in self.OPERATORS:
            raise ValueError(f"Unsupported operator: {operator_str}")
        self._operator = self.OPERATORS[operator_str]
        self._threshold = value

    def evaluate(self, state: Any, context: dict[str, Any]) -> bool:
        """Check if sensor value satisfies the comparison.

        Args:
            state: Current FSM state object (unused).
            context: Context dictionary containing sensor values.

        Returns:
            bool: True if comparison is satisfied, False otherwise.
        """
        # Context should contain entity states under 'entities' key
        entities = context.get("entities", {})
        try:
            current_value = float(entities.get(self._entity_id, 0))
        except (ValueError, TypeError):
            return False

        return self._operator(current_value, self._threshold)
