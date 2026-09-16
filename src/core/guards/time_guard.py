"""Time-based guard for declarative DSL."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any

from .base import BaseGuard


class TimeGuard(BaseGuard):
    """Guard that checks if current time is within a specified range.

    Attributes:
        start_time: Start time in "HH:MM" format.
        end_time: End time in "HH:MM" format.
    """

    def __init__(self, between: str) -> None:
        """Initialize time guard.

        Args:
            between: Time range in "HH:MM-HH:MM" format.
        """
        self._start_str, self._end_str = between.split("-")
        self._start = datetime.strptime(self._start_str, "%H:%M").time()
        self._end = datetime.strptime(self._end_str, "%H:%M").time()

    def evaluate(self, state: Any, context: dict[str, Any]) -> bool:
        """Check if current time is within the specified range.

        Args:
            state: Current FSM state object (unused).
            context: Context dictionary (unused).

        Returns:
            bool: True if current time is within range, False otherwise.
        """
        now = datetime.now().time()

        # Handle midnight crossing (e.g., 23:00-07:00)
        if self._start <= self._end:
            return self._start <= now <= self._end
        else:
            return now >= self._start or now <= self._end
