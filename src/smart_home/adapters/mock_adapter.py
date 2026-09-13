"""Mock Adapter for local testing without Home Assistant.

This adapter simulates Home Assistant behavior for local development
and testing. It prints state changes and service calls to console
with full trace_id support.

Features:
- Stores device states in memory
- Simulates Home Assistant service calls
- Emulates events from HA (motion_detected, manual_override)
- Logs all actions via loguru with trace_id support
- Supports state reset between tests
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger


class MockAdapter:
    """Mock adapter for simulating Home Assistant behavior during local testing.

    Stores device states in memory and allows emulating events from HA.

    Attributes:
        _states: Dictionary of device states {entity_id: state}.
        _fsm_engine: Reference to FSMEngine for event forwarding.
        _service_calls: Log of service calls for test verification.

    Usage:
        adapter = MockAdapter()
        await adapter.simulate_event("light.kitchen", "motion_detected")
        state = await adapter.get_state("light.kitchen")
        await adapter.call_service("light", "turn_on", "light.kitchen", {})
    """

    def __init__(self) -> None:
        """Initialize MockAdapter with empty state."""
        self._states: dict[str, Any] = {}
        self._fsm_engine: Any = None
        self._service_calls: list[dict[str, Any]] = []
        self.log = logger.bind(component="mock_adapter")

    def set_fsm_engine(self, fsm_engine: Any) -> None:
        """Set reference to FSMEngine for event forwarding.

        Args:
            fsm_engine: FSMEngine instance for event processing.
        """
        self._fsm_engine = fsm_engine
        self.log.debug(f"MockAdapter linked to FSMEngine: {fsm_engine}")

    async def get_state(self, entity_id: str) -> Any:
        """Get current state of a device.

        Args:
            entity_id: Device ID (e.g., "light.kitchen").

        Returns:
            Current device state or None if not found.
        """
        state = self._states.get(entity_id)
        self.log.debug(f"get_state({entity_id}) -> {state}")
        return state

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Simulate a Home Assistant service call.

        Updates device state in memory and logs the action.

        Args:
            domain: Service domain (e.g., "light").
            service: Service name (e.g., "turn_on", "turn_off").
            entity_id: Target device ID.
            data: Additional service data.
            context: Optional context dict (may contain trace_id).
        """
        data = data or {}
        context = context or {}
        trace_id = context.get("trace_id", "unknown")
        log = self.log.bind(trace_id=trace_id)

        # Log service call
        log_entry = {
            "domain": domain,
            "service": service,
            "entity_id": entity_id,
            "data": data,
        }
        self._service_calls.append(log_entry)

        log.info(f"call_service({domain}.{service}, {entity_id}, {data})")

        # Update state based on service
        if domain == "light":
            if service == "turn_on":
                self._states[entity_id] = "on"
                log.debug(f"{entity_id} turned ON")
            elif service == "turn_off":
                self._states[entity_id] = "off"
                log.debug(f"{entity_id} turned OFF")
            elif service == "toggle":
                current_state = self._states.get(entity_id, "off")
                self._states[entity_id] = "off" if current_state == "on" else "on"
                log.debug(f"{entity_id} toggled to {self._states[entity_id]}")

    async def simulate_event(
        self,
        entity_id: str,
        trigger: str,
        context: dict[str, Any] | None = None,
    ) -> bool:
        """Emulate an event coming from Home Assistant.

        Forwards the event to FSMEngine for processing.

        Args:
            entity_id: Device ID that triggered the event.
            trigger: Event type (e.g., "motion_detected", "manual_override").
            context: Additional event context.

        Returns:
            True if event was successfully processed, False otherwise.
        """
        if self._fsm_engine is None:
            self.log.warning(
                f"No FSMEngine attached, cannot process event '{trigger}' for {entity_id}"
            )
            return False

        context = context or {}
        trace_id = context.get("trace_id", "unknown")
        log = self.log.bind(trace_id=trace_id)

        log.info(f"simulate_event({entity_id}, {trigger}, {context})")

        try:
            result = await self._fsm_engine.trigger(entity_id, trigger, context)
            log.debug(f"Event '{trigger}' for {entity_id} processed, result={result}")
            return result
        except Exception as e:
            self.log.error(f"Failed to process event '{trigger}' for {entity_id}: {e}")
            return False

    def clear(self) -> None:
        """Reset adapter state between tests.

        Clears:
        - All device states
        - Service call log
        - All scheduled timers in FSMEngine (if available)
        """
        self._states.clear()
        self._service_calls.clear()

        # Cancel all timers in scheduler if FSMEngine is available
        if self._fsm_engine is not None and hasattr(self._fsm_engine, "scheduler"):
            self._fsm_engine.scheduler.cancel_all()

        self.log.debug("State cleared")

    def get_service_calls(
        self,
        domain: str | None = None,
        service: str | None = None,
        entity_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get service call log with optional filtering.

        Args:
            domain: Filter by domain (optional).
            service: Filter by service name (optional).
            entity_id: Filter by device ID (optional).

        Returns:
            List of service call records matching filters.
        """
        result = []
        for call in self._service_calls:
            if domain is not None and call.get("domain") != domain:
                continue
            if service is not None and call.get("service") != service:
                continue
            if entity_id is not None and call.get("entity_id") != entity_id:
                continue
            result.append(call)
        return result

    def count_service_calls(
        self,
        domain: str | None = None,
        service: str | None = None,
        entity_id: str | None = None,
    ) -> int:
        """Count service calls with filtering.

        Args:
            domain: Filter by domain (optional).
            service: Filter by service name (optional).
            entity_id: Filter by device ID (optional).

        Returns:
            Number of calls matching filters.
        """
        count = 0
        for call in self._service_calls:
            if domain is not None and call.get("domain") != domain:
                continue
            if service is not None and call.get("service") != service:
                continue
            if entity_id is not None and call.get("entity_id") != entity_id:
                continue
            count += 1
        return count
