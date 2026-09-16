"""Base guard classes for declarative DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseGuard(ABC):
    """Abstract base class for all guards."""

    @abstractmethod
    def evaluate(self, state: Any, context: dict[str, Any]) -> bool:
        """Evaluate the guard condition.

        Args:
            state: Current FSM state object.
            context: Context dictionary containing params, entity states, etc.

        Returns:
            bool: True if guard condition is satisfied, False otherwise.
        """
        pass
