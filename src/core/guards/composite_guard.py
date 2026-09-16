"""Composite guard for AND/OR logic in declarative DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from .base import BaseGuard


class CompositeGuard(BaseGuard):
    """Composite guard that combines multiple guards with AND/OR logic.

    Attributes:
        operator: "and" or "or" logical operator.
        guards: List of child guards to evaluate.
    """

    def __init__(self, operator: str, guards: list[BaseGuard]) -> None:
        """Initialize composite guard.

        Args:
            operator: Logical operator ("and" or "or").
            guards: List of child guards.

        Raises:
            ValueError: If operator is not "and" or "or".
        """
        if operator not in ("and", "or"):
            raise ValueError(f"Unsupported operator: {operator}")
        self._operator = operator
        self._guards = guards

    def evaluate(self, state: Any, context: dict[str, Any]) -> bool:
        """Evaluate all child guards and combine results.

        Args:
            state: Current FSM state object.
            context: Context dictionary.

        Returns:
            bool: Combined result of all guards.
        """
        if not self._guards:
            return True

        results = [guard.evaluate(state, context) for guard in self._guards]

        if self._operator == "and":
            return all(results)
        else:  # or
            return any(results)
