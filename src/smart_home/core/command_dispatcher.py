"""
Command Dispatcher Module for Smart Home Platform.

This module provides conflict resolution between FSMs by managing command intents
with priorities. It ensures that higher-priority commands take precedence over
lower-priority ones for the same device.
"""

from __future__ import annotations

from typing import Any, Dict, Protocol

from loguru import logger
from pydantic import BaseModel


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
    """
    device_id: str
    domain: str
    service: str
    data: dict[str, Any]
    priority: int
    source: str


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
    """
    
    def __init__(self, ha_adapter: HAAdapterProtocol) -> None:
        """
        Initialize CommandDispatcher.
        
        Args:
            ha_adapter: HAAdapter instance for calling Home Assistant services.
        """
        self._active_intents: Dict[str, CommandIntent] = {}
        self._ha_adapter = ha_adapter
    
    @property
    def active_intents(self) -> Dict[str, CommandIntent]:
        """Return the dictionary of active intents."""
        return self._active_intents
    
    async def submit(self, intent: CommandIntent) -> bool:
        """
        Submit a command intent for processing.
        
        If there's already an active intent for the same device with strictly
        higher priority, the new intent is ignored. Otherwise, the new intent
        becomes active and is sent to HAAdapter.
        
        Args:
            intent: The CommandIntent to submit.
        
        Returns:
            True if the intent was accepted and processed, False if ignored.
        """
        device_id = intent.device_id
        existing_intent = self._active_intents.get(device_id)
        
        # Check if there's an existing intent with strictly higher priority
        if existing_intent is not None and existing_intent.priority > intent.priority:
            logger.info(
                f"Ignored {intent.source} ({intent.priority}) because "
                f"{existing_intent.source} ({existing_intent.priority}) is active"
            )
            return False
        
        # Accept the new intent
        self._active_intents[device_id] = intent
        
        logger.info(
            f"Accepted intent from {intent.source} (priority={intent.priority}) "
            f"for device {device_id}"
        )
        
        # Call the service via HAAdapter
        await self._ha_adapter.call_service(
            domain=intent.domain,
            service=intent.service,
            entity_id=device_id,
            data=intent.data,
        )
        
        return True
    
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


if __name__ == "__main__":
    pass
