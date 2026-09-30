"""Тесты отписки от подписок с фильтром в EventBus (spec 006, FR-008, D-013).

Раньше ``unsubscribe()`` обслуживал только обычные подписки, поэтому подписки,
созданные фабрикой FSM по датчику движения, невозможно было снять: каждое
повторное создание автоматики добавляло ещё один обработчик, и один датчик
начинал вызывать несколько триггеров.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from core.events.event_bus import EventBus


@pytest.fixture
def bus() -> EventBus:
    """Создаёт шину событий для теста.

    Returns:
        Новая шина событий.
    """
    return EventBus()


class TestEventBusFilteredUnsubscribe:
    """Тесты отписки от подписок с фильтром."""

    async def test_unsubscribe_with_filter_should_stop_handler_calls_when_matching_filter(
        self, bus: EventBus
    ) -> None:
        """После отписки обработчик больше не вызывается."""
        calls: list[str] = []

        async def handler(event_type: str, payload: dict, trace_id: str | None = None) -> None:
            calls.append("called")

        bus.subscribe_with_filter("state_change", {"entity_id": "binary_sensor.motion"}, handler)
        bus.unsubscribe_with_filter("state_change", {"entity_id": "binary_sensor.motion"}, handler)

        await bus.publish("state_change", {"entity_id": "binary_sensor.motion"})

        assert calls == []

    async def test_unsubscribe_with_filter_should_keep_other_handlers(self, bus: EventBus) -> None:
        """Отписка одного обработчика не должна затрагивать другие."""
        first: list[str] = []
        second: list[str] = []

        async def handler_first(
            event_type: str, payload: dict, trace_id: str | None = None
        ) -> None:
            first.append("called")

        async def handler_second(
            event_type: str, payload: dict, trace_id: str | None = None
        ) -> None:
            second.append("called")

        bus.subscribe_with_filter(
            "state_change", {"entity_id": "binary_sensor.motion"}, handler_first
        )
        bus.subscribe_with_filter(
            "state_change", {"entity_id": "binary_sensor.motion"}, handler_second
        )
        bus.unsubscribe_with_filter(
            "state_change", {"entity_id": "binary_sensor.motion"}, handler_first
        )

        await bus.publish("state_change", {"entity_id": "binary_sensor.motion"})

        assert first == []
        assert second == ["called"]

    async def test_unsubscribe_with_filter_should_be_noop_when_not_subscribed(
        self, bus: EventBus
    ) -> None:
        """Отписка несуществующей подписки не должна поднимать исключение."""

        async def handler(event_type: str, payload: dict, trace_id: str | None = None) -> None:
            return None

        bus.unsubscribe_with_filter("state_change", {"entity_id": "nope"}, handler)

    async def test_unsubscribe_should_remove_filtered_subscription_by_handler(
        self, bus: EventBus
    ) -> None:
        """unsubscribe() по типу события должен снимать и отфильтрованные подписки."""
        calls: list[str] = []

        async def handler(event_type: str, payload: dict, trace_id: str | None = None) -> None:
            calls.append("called")

        bus.subscribe_with_filter("state_change", {"entity_id": "binary_sensor.motion"}, handler)
        bus.unsubscribe("state_change", handler)

        await bus.publish("state_change", {"entity_id": "binary_sensor.motion"})

        assert calls == []

    async def test_repeated_subscribe_unsubscribe_should_not_accumulate_handlers(
        self, bus: EventBus
    ) -> None:
        """Цикл подписки и отписки не должен накапливать обработчики (FR-008)."""
        calls: list[str] = []

        async def handler(event_type: str, payload: dict, trace_id: str | None = None) -> None:
            calls.append("called")

        for _ in range(5):
            bus.subscribe_with_filter(
                "state_change", {"entity_id": "binary_sensor.motion"}, handler
            )
            bus.unsubscribe_with_filter(
                "state_change", {"entity_id": "binary_sensor.motion"}, handler
            )

        bus.subscribe_with_filter("state_change", {"entity_id": "binary_sensor.motion"}, handler)
        await bus.publish("state_change", {"entity_id": "binary_sensor.motion"})

        assert calls == ["called"]
