"""
Command Dispatcher Module for Smart Home Platform.

This module provides conflict resolution between FSMs by managing command intents
with priorities. It ensures that higher-priority commands take precedence over
lower-priority ones for the same device.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any, Protocol

from loguru import logger
from pydantic import BaseModel, Field


class CommandIntent(BaseModel):
    """
    Represents a command intent with priority and source information.

    Attributes:
        device_id: ID of the target device (e.g., "light.kitchen").
        domain: Domain of the service (e.g., "light", "switch").
        service: Service name to call (e.g., "turn_on", "turn_off").
        data: Additional service data as a dictionary.
        priority: Priority level (higher number = higher priority).
        source: Name of the feature/module that created this intent.
        last_updated: Timestamp of the last activity (capture or refresh).
        ttl_seconds: Time-to-live since last activity; 0 means immediate
            expiry. Must be >= 0.
    """

    device_id: str
    domain: str
    service: str
    data: dict[str, Any]
    priority: int
    source: str
    last_updated: float = Field(default_factory=time.time)
    ttl_seconds: float = Field(default=3600.0, ge=0)

    def refresh(self) -> None:
        """Extend the intent's life by resetting ``last_updated`` to now."""
        self.last_updated = time.time()

    def is_expired(self) -> bool:
        """Return True if time since last activity exceeds ``ttl_seconds``."""
        return time.time() - self.last_updated > self.ttl_seconds


class MiddlewareProtocol(Protocol):
    """Protocol defining the interface for middleware."""

    async def process(self, intent: CommandIntent) -> CommandIntent | None:
        """
        Process a command intent.

        Args:
            intent: The CommandIntent to process.

        Returns:
            The processed CommandIntent if it should continue, or None to block.
        """
        ...


class HAAdapterProtocol(Protocol):
    """Protocol defining the interface for HAAdapter."""

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        """Call a Home Assistant service."""
        ...


class CommandDispatcher:
    """
    Dispatcher that resolves conflicts between FSM command intents.

    The dispatcher maintains active intents per device and uses priority-based
    conflict resolution. When multiple sources want to control the same device,
    the one with the highest priority wins.

    Attributes:
        _active_intents: Dictionary mapping device_id to active CommandIntent.
        _ha_adapter: HAAdapter instance for calling services.
        _middlewares: List of middleware instances to process intents.
    """

    def __init__(
        self,
        ha_adapter: HAAdapterProtocol,
        middlewares: list[MiddlewareProtocol] | None = None,
        cleanup_interval: float = 300.0,
    ) -> None:
        """
        Initialize CommandDispatcher.

        Args:
            ha_adapter: HAAdapter instance for calling Home Assistant services.
            middlewares: Optional list of middleware instances to process intents.
            cleanup_interval: Seconds between background TTL cleanup passes.
        """
        self._active_intents: dict[str, CommandIntent] = {}
        self._ha_adapter = ha_adapter
        self._middlewares: list[MiddlewareProtocol] = middlewares or []
        self._cleanup_interval = cleanup_interval
        self._lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    @property
    def active_intents(self) -> dict[str, CommandIntent]:
        """Return the dictionary of active intents."""
        return self._active_intents

    async def submit(self, intent: CommandIntent) -> bool:
        """
        Submit a command intent for processing.

        The intent is first processed through all middlewares in order.
        If any middleware returns None, the command is blocked.
        Otherwise, priority-based conflict resolution is applied.

        Args:
            intent: The CommandIntent to submit.

        Returns:
            True if the intent was accepted and processed, False if ignored or blocked.
        """
        try:
            # Process through middlewares first
            processed_intent = intent
            for middleware in self._middlewares:
                result = await middleware.process(processed_intent)
                if result is None:
                    logger.info(
                        f"Blocked intent from {intent.source} for device "
                        f"{intent.device_id} by middleware"
                    )
                    return False
                processed_intent = result

            device_id = processed_intent.device_id

            async with self._lock:
                existing_intent = self._active_intents.get(device_id)

                # Check if there's an existing intent with strictly higher priority
                if (
                    existing_intent is not None
                    and existing_intent.priority > processed_intent.priority
                ):
                    logger.info(
                        f"Ignored {processed_intent.source} ({processed_intent.priority}) because "
                        f"{existing_intent.source} ({existing_intent.priority}) is active"
                    )
                    return False

                # Preempt log: new intent takes over a lower-priority one
                if (
                    existing_intent is not None
                    and existing_intent.priority < processed_intent.priority
                ):
                    logger.info(
                        f"Preempt: {processed_intent.source} ({processed_intent.priority}) "
                        f"preempts {existing_intent.source} ({existing_intent.priority}) "
                        f"on device {device_id}"
                    )

                # Accept the new intent (first capture or re-capture)
                self._active_intents[device_id] = processed_intent
                processed_intent.refresh()

            logger.info(
                f"Accepted intent from {processed_intent.source} (priority={processed_intent.priority}) "
                f"for device {device_id}"
            )

            # Call the service via HAAdapter
            await self._ha_adapter.call_service(
                domain=processed_intent.domain,
                service=processed_intent.service,
                entity_id=device_id,
                data=processed_intent.data,
            )

            return True
        except Exception as e:
            logger.error(f"Error submitting CommandIntent: {e}")
            return False

    def release(self, device_id: str, source: str) -> bool:
        """
        Release an active intent for a device.

        This method allows FSMs to release their hold on a device, for example
        when a timer expires or a feature completes its operation.

        Only releases the intent if the source matches (prevents one feature
        from releasing another feature's intent).

        Args:
            device_id: ID of the device to release.
            source: Name of the feature requesting release.

        Returns:
            True if the intent was released, False if no matching intent existed.
        """
        existing_intent = self._active_intents.get(device_id)

        if existing_intent is None:
            logger.debug(f"No active intent for device {device_id}")
            return False

        if existing_intent.source != source:
            logger.warning(
                f"Release rejected: device {device_id} is controlled by "
                f"{existing_intent.source}, not {source}"
            )
            return False

        del self._active_intents[device_id]
        logger.info(f"Released device {device_id} from {source}")
        return True

    async def _cleanup_expired(self) -> int:
        """Force-release every expired intent under the dispatcher lock.

        Logs a WARNING in the contracts §4 format for each released intent.

        Returns:
            Number of intents force-released by this pass.
        """
        async with self._lock:
            expired = [
                device_id
                for device_id, intent in self._active_intents.items()
                if intent.is_expired()
            ]
            for device_id in expired:
                intent = self._active_intents.pop(device_id)
                idle_minutes = (time.time() - intent.last_updated) / 60.0
                logger.warning(
                    f"TTL EXPIRED: force-releasing {device_id} "
                    f"(source={intent.source}, idle {idle_minutes:.0f} min) "
                    f"— possible missing release() in FSM"
                )
            return len(expired)

    async def _cleanup_loop(self) -> None:
        """Background loop: sleep ``cleanup_interval``, then purge expired intents."""
        while True:
            await asyncio.sleep(self._cleanup_interval)
            await self._cleanup_expired()

    def start(self) -> None:
        """Start the TTL cleanup loop (idempotent: no-op if already running)."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            return
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop(self) -> None:
        """Stop the TTL cleanup loop (idempotent; suppresses CancelledError)."""
        task = self._cleanup_task
        self._cleanup_task = None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def add_middleware(self, middleware: MiddlewareProtocol) -> None:
        """
        Add a middleware instance to the processing chain.

        Allows adding middleware after the dispatcher has been created.
        Middleware are processed in the order they were added.

        Args:
            middleware: Middleware instance to add.
        """
        self._middlewares.append(middleware)


if __name__ == "__main__":
    pass
