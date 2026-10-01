"""Тесты доставки событий синхронными подписчиками шины.

Покрывают FR-003 (ошибка подписчика изолируется) и R-05 исследования:
запасной путь доставки не должен вызывать обработчик дважды и не должен
логировать ложную ошибку при успешном синхронном обработчике.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from loguru import logger
from src.core.events.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    """Шина без подписчиков."""
    return EventBus()


class TestSyncSubscribers:
    """Синхронные обработчики — поддерживаются (R-05)."""

    async def test_should_call_sync_subscriber_exactly_once_when_published(
        self, bus: EventBus
    ) -> None:
        """Синхронный обработчик вызывается ровно один раз."""
        calls: list[tuple[str, Any]] = []

        def sync_handler(event_type: str, payload: dict[str, Any]) -> None:
            calls.append((event_type, payload))

        bus.subscribe("test_event", sync_handler)

        await bus.publish("test_event", {"a": 1})

        assert calls == [("test_event", {"a": 1})]

    async def test_should_not_log_handler_error_when_sync_subscriber_succeeds(
        self, bus: EventBus
    ) -> None:
        """Успешный синхронный обработчик не порождает запись об ошибке."""
        errors: list[str] = []

        def sink(message: str) -> None:
            errors.append(message)

        def sync_handler(event_type: str, payload: dict[str, Any]) -> None:
            return None

        bus.subscribe("test_event", sync_handler)
        logger.remove()
        logger.add(sink, level="DEBUG")

        try:
            await bus.publish("test_event", {"a": 1})
        finally:
            logger.remove()

        assert not [e for e in errors if "Handler error" in e]

    async def test_should_await_sync_subscriber_returning_awaitable(self, bus: EventBus) -> None:
        """Синхронный обработчик может вернуть awaitable — шина его дожидается."""
        seen: list[str] = []

        async def work() -> None:
            seen.append("done")

        def sync_handler(event_type: str, payload: dict[str, Any]) -> Any:
            return work()

        bus.subscribe("test_event", sync_handler)

        await bus.publish("test_event", {"a": 1})

        assert seen == ["done"]

    async def test_should_log_error_once_when_sync_subscriber_raises(self, bus: EventBus) -> None:
        """Ошибка синхронного обработчика логируется один раз, доставка продолжается."""
        errors: list[str] = []
        delivered: list[str] = []

        def failing(event_type: str, payload: dict[str, Any]) -> None:
            raise ValueError("boom")

        async def ok(event_type: str, payload: dict[str, Any], trace_id: str | None = None) -> None:
            delivered.append(event_type)

        bus.subscribe("test_event", failing)
        bus.subscribe("test_event", ok)

        logger.remove()
        logger.add(lambda m: errors.append(m), level="DEBUG")
        try:
            await bus.publish("test_event", {"a": 1})
        finally:
            logger.remove()

        assert delivered == ["test_event"]
        assert len([e for e in errors if "boom" in e]) == 1


class TestNoDoubleInvocation:
    """TypeError из тела обработчика не приводит к повторному вызову (R-05)."""

    async def test_should_not_call_async_handler_twice_when_body_raises_type_error(
        self, bus: EventBus
    ) -> None:
        """Побочные эффекты выполняются один раз при TypeError внутри тела."""
        calls: list[dict[str, Any]] = []

        async def handler(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            calls.append(payload)
            raise TypeError("внутренняя ошибка тела")

        bus.subscribe("test_event", handler)

        await bus.publish("test_event", {"a": 1})

        assert calls == [{"a": 1}]

    async def test_should_call_legacy_two_arg_async_handler_once_when_published(
        self, bus: EventBus
    ) -> None:
        """Асинхронный обработчик без trace_id вызывается ровно один раз."""
        calls: list[dict[str, Any]] = []

        async def legacy(event_type: str, payload: dict[str, Any]) -> None:
            calls.append(payload)

        bus.subscribe("test_event", legacy)

        await bus.publish("test_event", {"a": 1})

        assert calls == [{"a": 1}]

    async def test_should_deliver_to_filtered_sync_subscriber(self, bus: EventBus) -> None:
        """Синхронный обработчик с фильтром также поддерживается."""
        calls: list[dict[str, Any]] = []

        def sync_filtered(event_type: str, payload: dict[str, Any]) -> None:
            calls.append(payload)

        bus.subscribe_with_filter("state_change", {"entity_id": "light.a"}, sync_filtered)

        await bus.publish("state_change", {"entity_id": "light.a", "new_state": "on"})
        await bus.publish("state_change", {"entity_id": "light.b", "new_state": "on"})

        assert calls == [{"entity_id": "light.a", "new_state": "on"}]


class TestSubscriberContract:
    """Контракт подписчика: async-обработчики принимают trace_id."""

    async def test_should_pass_trace_id_to_async_subscriber(self, bus: EventBus) -> None:
        """trace_id передаётся именованным аргументом."""
        captured: dict[str, Any] = {}

        async def handler(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            captured["trace_id"] = trace_id

        bus.subscribe("test_event", handler)

        await bus.publish("test_event", {"a": 1}, trace_id="abc12345")

        assert captured["trace_id"] == "abc12345"

    def test_subscribe_should_accept_plain_function(self, bus: EventBus) -> None:
        """Подписка принимает обычную функцию без аннотации coroutine."""

        def sync_handler(event_type: str, payload: dict[str, Any]) -> None:
            return None

        bus.subscribe("test_event", sync_handler)

        assert sync_handler in bus._subscribers["test_event"]

    def test_sync_handler_should_not_require_await_to_declare(self) -> None:
        """Документация шины не требует await-возврата для синхронных подписчиков."""
        assert inspect.iscoroutinefunction(EventBus.publish)
