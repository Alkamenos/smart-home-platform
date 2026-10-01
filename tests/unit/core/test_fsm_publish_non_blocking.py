"""
Тесты неблокирующей публикации перехода (FR-013, FR-014, SC-015).

Публикация перехода планируется отдельной задачей: медленный подписчик не
должен задерживать выполнение самого перехода, а задачи публикации не должны
оставаться висящими после остановки движка.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest
from src.core.events.event_bus import EventBus
from src.core.events.fsm_events import EVENT_FSM_TRANSITIONED

from core import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.kitchen_lighting_10"

SLOW_SUBSCRIBER_DELAY = 0.5


@pytest.fixture
def bus() -> EventBus:
    """Шина событий без подписчиков."""
    return EventBus()


@pytest.fixture
def engine(bus: EventBus) -> FSMEngine:
    """Движок состояний, подключённый к шине."""
    return FSMEngine(event_bus=bus)


def register_simple_fsm(engine: FSMEngine) -> None:
    """Зарегистрировать простой автомат освещения.

    Args:
        engine: Движок состояний.
    """
    engine.register_definition(
        FSMDefinition(
            entity_id=FSM_ID,
            initial_state="OFF",
            states=("OFF", "ON_MOTION"),
            transitions=(
                Transition(from_state="OFF", to_state="ON_MOTION", trigger="motion_detected"),
            ),
            target_device_id="light.kitchen",
        )
    )


class TestNonBlockingPublish:
    """Переход не ждёт подписчиков (FR-014, SC-015)."""

    async def test_should_complete_transition_faster_than_slow_subscriber(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Переход завершается быстрее, чем длительность медленного подписчика."""

        async def slow(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            await asyncio.sleep(SLOW_SUBSCRIBER_DELAY)

        bus.subscribe(EVENT_FSM_TRANSITIONED, slow)
        register_simple_fsm(engine)

        started = time.perf_counter()
        result = await engine.trigger(FSM_ID, "motion_detected")
        elapsed = time.perf_counter() - started

        assert result is True
        assert elapsed < SLOW_SUBSCRIBER_DELAY

    async def test_should_deliver_to_slow_subscriber_eventually(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Событие всё же доходит до медленного подписчика."""
        delivered: list[str] = []

        async def slow(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            await asyncio.sleep(SLOW_SUBSCRIBER_DELAY)
            delivered.append(event_type)

        bus.subscribe(EVENT_FSM_TRANSITIONED, slow)
        register_simple_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        await asyncio.sleep(SLOW_SUBSCRIBER_DELAY * 2)

        assert delivered == [EVENT_FSM_TRANSITIONED]

    async def test_should_not_delay_transition_chain_when_many_subscribers(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Число подписчиков не влияет на длительность перехода."""

        async def slow(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            await asyncio.sleep(SLOW_SUBSCRIBER_DELAY)

        for _ in range(5):
            bus.subscribe(EVENT_FSM_TRANSITIONED, slow)
        register_simple_fsm(engine)

        started = time.perf_counter()
        await engine.trigger(FSM_ID, "motion_detected")
        elapsed = time.perf_counter() - started

        assert elapsed < SLOW_SUBSCRIBER_DELAY


class TestTrackedPublishTasks:
    """Задачи публикации отслеживаются и гасятся при остановке (FR-012)."""

    async def test_should_have_no_pending_publish_tasks_after_shutdown(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """После shutdown висящих задач публикации не остаётся."""

        async def slow(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            await asyncio.sleep(SLOW_SUBSCRIBER_DELAY * 2)

        bus.subscribe(EVENT_FSM_TRANSITIONED, slow)
        register_simple_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        pending_before = len(engine._publish_tasks)
        assert pending_before == 1

        await engine.shutdown()

        assert engine._publish_tasks == set()

    async def test_should_remove_finished_task_from_tracking(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Завершившаяся задача публикации убирается из отслеживания."""
        delivered: list[str] = []

        async def fast(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            delivered.append(event_type)

        bus.subscribe(EVENT_FSM_TRANSITIONED, fast)
        register_simple_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected")
        await asyncio.sleep(0.01)

        assert delivered == [EVENT_FSM_TRANSITIONED]
        assert engine._publish_tasks == set()


class TestTraceCorrelation:
    """trace_id события совпадает с журналом перехода (R-02)."""

    async def test_should_publish_event_with_trigger_trace_id(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Переданный trace_id доходит до подписчика."""
        captured: list[str | None] = []

        async def observer(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            captured.append(payload["trace_id"])

        bus.subscribe(EVENT_FSM_TRANSITIONED, observer)
        register_simple_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected", trace_id="deadbeef")

        await asyncio.sleep(0)
        assert captured == ["deadbeef"]

    async def test_should_publish_trace_id_into_bus_publication_log(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Публикация в шину выполняется с тем же trace_id."""
        seen: list[str | None] = []

        original_publish = bus.publish

        async def spy(event_type: str, payload: Any = None, trace_id: str | None = None) -> None:
            seen.append(trace_id)
            await original_publish(event_type, payload, trace_id)

        bus.publish = spy  # type: ignore[method-assign]
        register_simple_fsm(engine)

        await engine.trigger(FSM_ID, "motion_detected", trace_id="feedface")

        await asyncio.sleep(0)
        assert "feedface" in seen
