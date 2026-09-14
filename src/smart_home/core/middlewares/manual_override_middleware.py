"""
Manual Override Middleware for Smart Home Platform.

This module provides middleware that blocks automation when a user has
recently manually controlled a device through Home Assistant UI.
"""

from __future__ import annotations

import time

from loguru import logger

from ..command_dispatcher import CommandIntent


class ManualOverrideMiddleware:
    """
    Middleware that blocks automation after manual user intervention.

    When a user manually controls a device via Home Assistant UI (detected
    by context.user_id), this middleware starts a lockout period during which
    automated commands for that device are blocked.

    Attributes:
        lockout_seconds: Duration of the lockout period in seconds.
        _manual_overrides: Dictionary mapping entity_id to timestamp of last manual control.
    """

    def __init__(self, lockout_seconds: int = 3600) -> None:
        """
        Initialize ManualOverrideMiddleware.

        Args:
            lockout_seconds: Duration of lockout period after manual control.
                            Default is 3600 seconds (1 hour).
        """
        self.lockout_seconds = lockout_seconds
        self._manual_overrides: dict[str, float] = {}  # entity_id -> timestamp

    async def process(self, intent: CommandIntent) -> CommandIntent | None:
        """
        Process a command intent, blocking automation during manual override.

        If the device was manually controlled within the lockout period and
        the incoming command is from an automated source (not manual/user),
        the command is blocked.

        Args:
            intent: The CommandIntent to process.

        Returns:
            The intent if it should be processed, None if it should be blocked.
        """
        entity_id = intent.device_id
        last_manual = self._manual_overrides.get(entity_id)

        # Check if there's a recent manual override
        if (
            last_manual
            and (time.time() - last_manual) < self.lockout_seconds
            and intent.source.lower() not in ("manual", "user")
        ):
            # Block automated commands during lockout
            logger.info(f"Blocked {intent.source} for {entity_id}: manual override active")
            return None  # Block the command

        return intent  # Allow the command

    def register_manual_override(self, entity_id: str) -> None:
        """
        Register a manual override for a device.

        This method should be called when HAAdapter detects manual user control
        (e.g., when context.user_id exists in a state change event).

        Args:
            entity_id: The ID of the device that was manually controlled.
        """
        self._manual_overrides[entity_id] = time.time()
        logger.info(f"Registered manual override for {entity_id}")
