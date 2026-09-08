"""Event bus module for smart home core."""

import uuid
from typing import Any, Callable, Coroutine

from loguru import logger


class EventBus:
    """Async event bus for publishing events to subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Coroutine[Any, Any, None]]]] = {}

    def subscribe(
        self, event_type: str, handler: Callable[..., Coroutine[Any, Any, None]]
    ) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(
        self, event_type: str, handler: Callable[..., Coroutine[Any, Any, None]]
    ) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(handler)

    async def publish(self, event_type: str, payload: Any = None, trace_id: str | None = None) -> None:
        """Publish an event to all subscribers.
        
        Args:
            event_type: Type of the event.
            payload: Event payload data.
            trace_id: Optional trace ID for logging correlation. 
                      If not provided, generates a short UUID.
        """
        if trace_id is None:
            trace_id = str(uuid.uuid4())[:8]
        
        # Bind trace_id to loguru context for this event
        log_context = logger.bind(trace_id=trace_id)
        
        log_context.info(f"Publishing event: {event_type}")
        
        handlers = self._subscribers.get(event_type, [])
        
        for handler in handlers:
            try:
                await handler(event_type, payload, trace_id=trace_id)
            except TypeError:
                # Handler doesn't accept trace_id kwarg, call without it
                try:
                    await handler(event_type, payload)
                except Exception as e:
                    log_context.error(f"Handler error for event {event_type}: {e}")
            except Exception as e:
                log_context.error(f"Handler error for event {event_type}: {e}")
