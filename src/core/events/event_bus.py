"""Event bus module for smart home core."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

import contextlib
import inspect
import uuid
from collections.abc import Callable
from typing import Any

from loguru import logger


# Обработчик события: async-функция (предпочтительно) либо обычная функция,
# возвращающая None. Возвращённый awaitable шина дожидается (R-05).
EventHandler = Callable[..., Any]


def _accepts_trace_id(handler: EventHandler) -> bool:
    """Проверить, принимает ли обработчик именованный аргумент ``trace_id``.

    Args:
        handler: Обработчик события.

    Returns:
        True, если обработчик явно принимает ``trace_id`` или принимает
        произвольные именованные аргументы. False, если сигнатура не содержит
        такого параметра или её не удалось получить.
    """
    try:
        signature = inspect.signature(handler)
    except (TypeError, ValueError):
        # Обработчик без доступной сигнатуры — считаем, что trace_id примет.
        return True

    for parameter in signature.parameters.values():
        if parameter.name == "trace_id":
            return True
        if parameter.kind is inspect.Parameter.VAR_KEYWORD:
            return True
    return False


async def _invoke_handler(
    handler: EventHandler,
    event_type: str,
    payload: Any,
    trace_id: str,
) -> None:
    """Вызвать обработчик события, дождавшись результата.

    Ошибка несовместимости сигнатуры определяется **до** вызова, поэтому
    TypeError, возникший внутри тела обработчика, не приводит к повторному
    вызову и не маскируется (R-05).

    Args:
        handler: Обработчик события.
        event_type: Тип события.
        payload: Полезная нагрузка события.
        trace_id: Идентификатор трассы.
    """
    result = (
        handler(event_type, payload, trace_id=trace_id)
        if _accepts_trace_id(handler)
        else handler(event_type, payload)
    )
    if inspect.isawaitable(result):
        await result


class EventBus:
    """Async event bus for publishing events to subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[EventHandler]] = {}
        self._filtered_subscribers: list[tuple[str, dict, EventHandler]] = []

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: str, handler: EventHandler) -> None:
        """Unsubscribe a handler from an event type.

        Снимает как обычные подписки, так и подписки с фильтром: обработчик
        идентифицируется по ссылке (spec 006, FR-008).

        Args:
            event_type: Тип события.
            handler: Обработчик для отписки.
        """
        if event_type in self._subscribers:
            with contextlib.suppress(ValueError):
                self._subscribers[event_type].remove(handler)

        self._filtered_subscribers = [
            entry
            for entry in self._filtered_subscribers
            if not (entry[0] == event_type and entry[2] is handler)
        ]

    def unsubscribe_with_filter(
        self,
        event_type: str,
        filter_params: dict,
        handler: EventHandler,
    ) -> None:
        """Unsubscribe a handler that was subscribed with a filter.

        Args:
            event_type: Тип события.
            filter_params: Параметры фильтра, с которыми была подписка.
            handler: Обработчик для отписки.
        """
        self._filtered_subscribers = [
            entry
            for entry in self._filtered_subscribers
            if not (entry[0] == event_type and entry[1] == filter_params and entry[2] is handler)
        ]

    def subscribe_with_filter(
        self,
        event_type: str,
        filter_params: dict,
        handler: EventHandler,
    ) -> None:
        """Subscribe a handler to an event type with filter parameters.

        The handler will be called only when the event payload matches the filter_params.
        Matching is done by checking if all keys in filter_params exist in the payload
        and have the same values.

        Args:
            event_type: Type of the event to subscribe to.
            filter_params: Dictionary of parameters that must match the event payload.
            handler: Handler to call when event matches filter.
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

    async def _dispatch(
        self,
        handler: EventHandler,
        event_type: str,
        payload: Any,
        trace_id: str,
        log: Any,
        prefix: str,
    ) -> None:
        """Вызвать обработчик, изолировав его ошибку.

        Args:
            handler: Обработчик события.
            event_type: Тип события.
            payload: Полезная нагрузка события.
            trace_id: Идентификатор трассы.
            log: Привязанный к трассе логгер.
            prefix: Префикс сообщения об ошибке.
        """
        try:
            await _invoke_handler(handler, event_type, payload, trace_id)
        except Exception as e:  # noqa: BLE001 - изоляция подписчика (FR-003)
            log.error(f"{prefix} for event {event_type}: {e}")

    async def publish(
        self, event_type: str, payload: Any = None, trace_id: str | None = None
    ) -> None:
        """Publish an event to all subscribers.

        Подписчики вызываются последовательно: сначала обычные в порядке
        подписки, затем отфильтрованные. Порядок доставки не менялся (R-05).

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
        handlers = list(self._subscribers.get(event_type, []))

        for handler in handlers:
            await self._dispatch(
                handler, event_type, payload, trace_id, log_context, "Handler error"
            )

        # Call filtered subscribers if payload matches
        if isinstance(payload, dict):
            for sub_event_type, filter_params, handler in list(self._filtered_subscribers):
                if sub_event_type == event_type and self._matches_filter(filter_params, payload):
                    await self._dispatch(
                        handler,
                        event_type,
                        payload,
                        trace_id,
                        log_context,
                        "Filtered handler error",
                    )
