"""
FSM (Finite State Machine) Engine for Smart Home Platform.

This module provides an immutable, async-first FSM engine designed for
smart home automation scenarios with support for guards, actions, timeouts,
and debounce protection.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Optional

from loguru import logger


@dataclass(frozen=True)
class State:
    """
    Immutable representation of the current state of an entity.

    Attributes:
        current_state: The name/identifier of the current state.
        entered_at: Unix timestamp when this state was entered.
        context: Dictionary for internal memory (e.g., last manual intervention time).
    """
    current_state: str
    entered_at: float
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    """
    Immutable definition of a state transition.

    Attributes:
        from_state: The source state for this transition.
        to_state: The destination state after transition.
        trigger: The event name that triggers this transition.
        guard: Optional callable condition function that must return True.
        action: Optional callable action function to execute on transition.
        timeout_sec: Optional timeout in seconds to auto-trigger 'timeout' event.
    """
    from_state: str
    to_state: str
    trigger: str
    guard: Optional[Callable[..., bool]] = None
    action: Optional[Callable[..., Any]] = None
    timeout_sec: Optional[float] = None


@dataclass(frozen=True)
class FSMDefinition:
    """
    Immutable definition of a Finite State Machine.

    Attributes:
        entity_id: Unique identifier for the entity using this FSM.
        initial_state: The starting state name.
        states: Tuple of valid state names.
        transitions: Tuple of Transition objects defining state changes.
        debounce_sec: Minimum time between state changes to prevent bouncing.
    """
    entity_id: str
    initial_state: str
    states: tuple[str, ...]
    transitions: tuple[Transition, ...]
    debounce_sec: float = 0.0


class FSMEngine:
    """
    Async FSM Engine for smart home entities.

    Manages state machines for multiple entities with support for:
    - Guard conditions evaluation
    - Action execution on transitions
    - Timeout-based automatic transitions
    - Debounce protection against rapid state changes
    - Comprehensive logging via loguru
    """

    def __init__(self) -> None:
        self._states: dict[str, State] = {}
        self._definitions: dict[str, FSMDefinition] = {}
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._last_transition_time: dict[str, float] = {}
        self._guards: dict[str, Callable[..., bool]] = {}
        self._actions: dict[str, Callable[..., Any]] = {}

    def register_definition(self, definition: FSMDefinition) -> None:
        """Register an FSM definition for an entity."""
        self._definitions[definition.entity_id] = definition
        if definition.entity_id not in self._states:
            self._states[definition.entity_id] = State(
                current_state=definition.initial_state,
                entered_at=asyncio.get_event_loop().time(),
                context={}
            )
        logger.debug(f"Registered FSM for entity {definition.entity_id} with initial state '{definition.initial_state}'")

    def register_guard(self, name: str, guard_fn: Callable[..., bool]) -> None:
        """Register a guard condition function by name."""
        self._guards[name] = guard_fn
        logger.debug(f"Registered guard '{name}'")

    def register_action(self, name: str, action_fn: Callable[..., Any]) -> None:
        """Register an action function by name."""
        self._actions[name] = action_fn
        logger.debug(f"Registered action '{name}'")

    def get_state(self, entity_id: str) -> Optional[State]:
        """Get the current state of an entity."""
        return self._states.get(entity_id)

    async def _cancel_timers(self, entity_id: str, log: Any | None = None) -> None:
        """Cancel any pending timers for an entity.
        
        Args:
            entity_id: ID of the entity whose timers should be cancelled.
            log: Optional logger instance with trace_id bound.
        """
        if log is None:
            log = logger
        if entity_id in self._timers:
            timer_task = self._timers[entity_id]
            if not timer_task.done():
                timer_task.cancel()
                try:
                    await timer_task
                except asyncio.CancelledError:
                    pass
            del self._timers[entity_id]
            log.debug(f"Cancelled timers for entity {entity_id}")

    def _evaluate_guard(self, guard: Optional[Callable[..., bool]], context: dict[str, Any], log: Any | None = None) -> bool:
        """Evaluate a guard condition if specified.
        
        Args:
            guard: Guard function to evaluate.
            context: Context dictionary for the guard.
            log: Optional logger instance with trace_id bound.
        
        Returns:
            True if guard passes or is None, False otherwise.
        """
        if log is None:
            log = logger
        if guard is None:
            return True
        
        try:
            result = guard(context)
            log.debug(f"Guard '{guard.__name__}' evaluated to {result}")
            return result
        except Exception as e:
            log.error(f"Guard '{guard.__name__}' raised exception: {e}, denying transition")
            return False

    async def _execute_action(self, action: Optional[Callable[..., Any]], context: dict[str, Any], log: Any | None = None) -> None:
        """Execute an action if specified.
        
        Args:
            action: Action function to execute.
            context: Context dictionary for the action.
            log: Optional logger instance with trace_id bound.
        """
        if log is None:
            log = logger
        if action is None:
            return
        
        try:
            result = action(context)
            if asyncio.iscoroutine(result):
                await result
            log.debug(f"Action '{action.__name__}' executed successfully")
        except Exception as e:
            log.error(f"Action '{action.__name__}' raised exception: {e}")

    async def trigger(self, entity_id: str, event: str, external_ctx: Optional[dict[str, Any]] = None, trace_id: str | None = None) -> bool:
        """
        Trigger an event for an entity's FSM.

        Args:
            entity_id: The entity identifier.
            event: The event name to trigger.
            external_ctx: Optional external context to merge with internal context.
            trace_id: Optional trace ID for logging correlation. If not provided,
                      generates a short UUID.

        Returns:
            True if a transition occurred, False otherwise.
        """
        # Generate or use provided trace_id
        if trace_id is None:
            trace_id = str(uuid.uuid4())[:8]
        
        # Bind trace_id to logger for this trigger
        log = logger.bind(trace_id=trace_id)
        
        # Cancel any existing timers before processing new trigger
        await self._cancel_timers(entity_id, log)

        if entity_id not in self._definitions:
            log.warning(f"No FSM definition found for entity {entity_id}")
            return False

        definition = self._definitions[entity_id]
        
        if entity_id not in self._states:
            log.error(f"No state found for entity {entity_id}")
            return False

        current_state = self._states[entity_id]
        now = asyncio.get_event_loop().time()

        # Check debounce
        if entity_id in self._last_transition_time:
            elapsed = now - self._last_transition_time[entity_id]
            if elapsed < definition.debounce_sec:
                log.debug(
                    f"Entity {entity_id}: Debounce active ({elapsed:.3f}s < {definition.debounce_sec}s), "
                    f"ignoring event '{event}'"
                )
                return False

        # Find matching transitions
        matching_transitions = [
            t for t in definition.transitions
            if t.from_state == current_state.current_state and t.trigger == event
        ]

        if not matching_transitions:
            log.debug(f"Entity {entity_id}: No transitions for event '{event}' from state '{current_state.current_state}'")
            return False

        # Merge contexts
        merged_context = {**current_state.context}
        if external_ctx:
            merged_context.update(external_ctx)

        # Process transitions (first valid one wins)
        for transition in matching_transitions:
            # Evaluate guard
            if not self._evaluate_guard(transition.guard, merged_context, log):
                log.debug(
                    f"Entity {entity_id}: Guard '{transition.guard}' failed for transition "
                    f"'{current_state.current_state}' -> '{transition.to_state}'"
                )
                continue

            # Execute action
            await self._execute_action(transition.action, merged_context, log)

            # Create new state
            new_state = State(
                current_state=transition.to_state,
                entered_at=now,
                context=merged_context
            )

            # Update state
            self._states[entity_id] = new_state
            self._last_transition_time[entity_id] = now

            log.info(
                f"Entity {entity_id}: Transition '{current_state.current_state}' -> '{transition.to_state}' "
                f"triggered by '{event}'" +
                (f" (guard: {transition.guard})" if transition.guard else "") +
                (f" (action: {transition.action})" if transition.action else "")
            )

            # Schedule timeout if specified
            if transition.timeout_sec is not None and transition.timeout_sec > 0:
                self._timers[entity_id] = asyncio.create_task(
                    self._timeout_handler(entity_id, transition.timeout_sec, log)
                )
                log.debug(
                    f"Entity {entity_id}: Scheduled timeout transition in {transition.timeout_sec}s"
                )

            return True

        log.debug(f"Entity {entity_id}: No valid transitions for event '{event}'")
        return False

    async def _timeout_handler(self, entity_id: str, timeout_sec: float, log: Any | None = None) -> None:
        """Handle timeout-based transitions."""
        if log is None:
            log = logger
        try:
            await asyncio.sleep(timeout_sec)
            log.debug(f"Entity {entity_id}: Timeout expired, triggering 'timeout' event")
            await self.trigger(entity_id, "timeout", trace_id=log.context.get("trace_id"))
        except asyncio.CancelledError:
            log.debug(f"Entity {entity_id}: Timeout cancelled")
            raise

    async def shutdown(self) -> None:
        """Shutdown the engine, cancelling all pending timers."""
        for entity_id in list(self._timers.keys()):
            await self._cancel_timers(entity_id)
        logger.info("FSM Engine shutdown complete")
