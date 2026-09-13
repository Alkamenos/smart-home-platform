"""Event bus module for smart home core."""

import uuid
from typing import Any, Callable, Coroutine

from loguru import logger


class EventBus:
    """Async event bus for publishing events to subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[..., Coroutine[Any, Any, None]]]] = {}
        self._filtered_subscribers: list[tuple[str, dict, Callable[..., Coroutine[Any, Any, None]]]] = []

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

    def subscribe_with_filter(
        self,
        event_type: str,
        filter_params: dict,
        handler: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe a handler to an event type with filter parameters.
        
        The handler will be called only when the event payload matches the filter_params.
        Matching is done by checking if all keys in filter_params exist in the payload
        and have the same values.
        
        Args:
            event_type: Type of the event to subscribe to.
            filter_params: Dictionary of parameters that must match the event payload.
            handler: Async handler function to call when event matches filter.
        """
        self._filtered_subscribers.append((event_type, filter_params, handler))

    def _matches_filter(self, filter_params: dict, payload: Any) -> bool:
        """Check if payload matches filter parameters.
        
        Args:
            filter_params: Dictionary of parameters to match.
            payload: Event payload data.
            
        Returns:
            True if all filter_params match the payload, False otherwise.
        """
        if not isinstance(payload, dict):
            return False
        
        for key, value in filter_params.items():
            if key not in payload or payload[key] != value:
                return False
        return True

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
        
        # Call regular subscribers
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
        
        # Call filtered subscribers if payload matches
        if isinstance(payload, dict):
            for sub_event_type, filter_params, handler in self._filtered_subscribers:
                if sub_event_type == event_type and self._matches_filter(filter_params, payload):
                    try:
                        await handler(event_type, payload, trace_id=trace_id)
                    except TypeError:
                        try:
                            await handler(event_type, payload)
                        except Exception as e:
                            log_context.error(f"Filtered handler error for event {event_type}: {e}")
                    except Exception as e:
                        log_context.error(f"Filtered handler error for event {event_type}: {e}")
