"""
TTL-тесты командных интентов (спецификация 003, US3, FR-008…FR-013).

Сценарии quickstart 3 / research R4 / data-model.md:
1. истёкший интент освобождается cleanup'ом, новый интент проходит;
2. refresh()/повторный захват продлевает жизнь — ложных срабатываний нет;
3. конкурентные submit() не дают гонок (asyncio.Lock, FR-011);
4. preempt по приоритету сохраняет существующее поведение (FR-012);
5. force-release пишет WARNING формата contracts §4 (FR-009);
6. start() идемпотентен, stop() не оставляет задач;
+ валидация ttl_seconds >= 0 (data-model.md).
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from typing import Any

import pytest


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import CommandDispatcher, CommandIntent


class MockHAAdapter:
    """Mock HAAdapter recording call_service invocations."""

    def __init__(self) -> None:
        self.call_service_calls: list[dict[str, Any]] = []

    async def call_service(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> bool:
        self.call_service_calls.append(
            {"domain": domain, "service": service, "entity_id": entity_id}
        )
        return True


@pytest.fixture
def adapter() -> MockHAAdapter:
    return MockHAAdapter()


@pytest.fixture
def dispatcher(adapter: MockHAAdapter) -> CommandDispatcher:
    return CommandDispatcher(ha_adapter=adapter, middlewares=[])


def make_intent(
    source: str = "source_a",
    device_id: str = "light.kitchen",
    priority: int = 10,
    ttl_seconds: float = 3600.0,
) -> CommandIntent:
    return CommandIntent(
        device_id=device_id,
        domain="light",
        service="turn_on",
        data={"brightness": 100},
        priority=priority,
        source=source,
        ttl_seconds=ttl_seconds,
    )


class TestTTLExpiry:
    """Точки 1 и 2: истечение и продление жизни интента."""

    @pytest.mark.asyncio
    async def test_expired_intent_freed_and_new_intent_passes(
        self, dispatcher: CommandDispatcher, adapter: MockHAAdapter
    ) -> None:
        """Точка 1: ttl_seconds=0.05 → cleanup освобождает устройство."""
        intent = make_intent(source="source_a", ttl_seconds=0.05)
        assert await dispatcher.submit(intent) is True

        await asyncio.sleep(0.06)
        freed = await dispatcher._cleanup_expired()

        assert freed == 1
        assert "light.kitchen" not in dispatcher.active_intents

        new_intent = make_intent(source="source_b")
        assert await dispatcher.submit(new_intent) is True
        assert dispatcher.active_intents["light.kitchen"].source == "source_b"
        assert len(adapter.call_service_calls) == 2

    @pytest.mark.asyncio
    async def test_refresh_extends_life(self, dispatcher: CommandDispatcher) -> None:
        """Точка 2: refresh()/повторный захват продлевает — cleanup не срабатывает."""
        intent = make_intent(source="source_a", ttl_seconds=0.2)
        assert await dispatcher.submit(intent) is True

        await asyncio.sleep(0.12)
        # Повторный захват тем же intent → refresh() в submit()
        assert await dispatcher.submit(intent) is True

        await asyncio.sleep(0.12)
        assert await dispatcher._cleanup_expired() == 0
        assert "light.kitchen" in dispatcher.active_intents

        # Прямой refresh() тоже продлевает
        await asyncio.sleep(0.12)
        intent.refresh()
        await asyncio.sleep(0.05)
        assert await dispatcher._cleanup_expired() == 0
        assert "light.kitchen" in dispatcher.active_intents

    @pytest.mark.asyncio
    async def test_expired_then_refreshed_by_resubmit_is_not_freed(
        self, dispatcher: CommandDispatcher
    ) -> None:
        """Интент, истёкший бы без refresh, переживает cleanup после повторного захвата."""
        intent = make_intent(source="source_a", ttl_seconds=0.15)
        assert await dispatcher.submit(intent) is True

        await asyncio.sleep(0.16)
        assert intent.is_expired() is True
        assert await dispatcher.submit(intent) is True
        assert intent.is_expired() is False

        assert await dispatcher._cleanup_expired() == 0
        assert "light.kitchen" in dispatcher.active_intents

    def test_is_expired_semantics(self) -> None:
        """is_expired(): age > ttl_seconds; ttl=0 допустимо (немедленное истечение)."""
        intent = make_intent(ttl_seconds=0.0)
        time.sleep(0.001)
        assert intent.is_expired() is True

        fresh = make_intent(ttl_seconds=3600.0)
        assert fresh.is_expired() is False

    def test_negative_ttl_rejected(self) -> None:
        """data-model: ttl_seconds >= 0 (отрицательный — ошибка валидации)."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            make_intent(ttl_seconds=-1.0)


class TestConcurrencyAndPreempt:
    """Точки 3 и 4: гонки и семантика приоритетов."""

    @pytest.mark.asyncio
    async def test_concurrent_submits_no_race(self, dispatcher: CommandDispatcher) -> None:
        """Точка 3: 10 конкурентных submit() → один активный интент, без исключений."""
        assert isinstance(dispatcher._lock, asyncio.Lock)

        results = await asyncio.gather(
            *[dispatcher.submit(make_intent(source=f"source_{i}", priority=10)) for i in range(10)]
        )

        assert all(isinstance(r, bool) for r in results)
        active = [k for k in dispatcher.active_intents if k == "light.kitchen"]
        assert len(active) == 1
        assert dispatcher.active_intents["light.kitchen"].source.startswith("source_")

    @pytest.mark.asyncio
    async def test_preempt_priority_semantics_unchanged(
        self, dispatcher: CommandDispatcher, adapter: MockHAAdapter
    ) -> None:
        """Точка 4: более высокий приоритет вытесняет, более низкий — отклоняется."""
        low = make_intent(source="motion_lighting", priority=10)
        assert await dispatcher.submit(low) is True

        high = make_intent(source="night_light", priority=20)
        assert await dispatcher.submit(high) is True
        assert dispatcher.active_intents["light.kitchen"].source == "night_light"
        assert len(adapter.call_service_calls) == 2

        rejected = make_intent(source="other_low", priority=5)
        assert await dispatcher.submit(rejected) is False
        assert dispatcher.active_intents["light.kitchen"].source == "night_light"
        assert len(adapter.call_service_calls) == 2


class TestForceReleaseLogging:
    """Точка 5: WARNING формата contracts §4 при TTL force-release."""

    @pytest.mark.asyncio
    async def test_cleanup_warns_in_contracts_format(self, dispatcher: CommandDispatcher) -> None:
        from loguru import logger

        records: list[str] = []
        sink_id = logger.add(
            lambda message: records.append(str(message)),
            level="WARNING",
            format="{message}",
        )
        try:
            intent = make_intent(source="night_light", ttl_seconds=0.05)
            assert await dispatcher.submit(intent) is True
            await asyncio.sleep(0.06)
            freed = await dispatcher._cleanup_expired()
        finally:
            logger.remove(sink_id)

        assert freed == 1
        pattern = (
            r"TTL EXPIRED: force-releasing light\.kitchen "
            r"\(source=night_light, idle \d+ min\) — possible missing release\(\) in FSM"
        )
        assert any(re.search(pattern, r) for r in records), (
            f"нет WARNING формата contracts §4; записи: {records}"
        )


class TestLifecycle:
    """Точка 6: start()/stop() — идемпотентность и отсутствие висящих задач."""

    @pytest.mark.asyncio
    async def test_start_idempotent_and_stop_leaves_no_tasks(self, adapter: MockHAAdapter) -> None:
        dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[], cleanup_interval=0.05)

        def cleanup_tasks() -> list[asyncio.Task]:
            current = asyncio.current_task()
            return [
                t
                for t in asyncio.all_tasks()
                if t is not current and not t.done() and "cleanup_loop" in repr(t.get_coro())
            ]

        try:
            dispatcher.start()
            dispatcher.start()
            assert len(cleanup_tasks()) == 1, "start() должен быть идемпотентен"

            # Цикл реально работает: истёкший интент освобождается без ручного вызова
            intent = make_intent(source="source_a", ttl_seconds=0.05)
            assert await dispatcher.submit(intent) is True
            await asyncio.sleep(0.2)
            assert "light.kitchen" not in dispatcher.active_intents

            await dispatcher.stop()
            assert not cleanup_tasks(), "stop() оставил висящие задачи"

            await dispatcher.stop()  # повторный stop безопасен
        finally:
            await dispatcher.stop()

        assert not cleanup_tasks()

    @pytest.mark.asyncio
    async def test_stop_without_start_is_safe(self, adapter: MockHAAdapter) -> None:
        dispatcher = CommandDispatcher(ha_adapter=adapter, middlewares=[])
        await dispatcher.stop()
        assert dispatcher._cleanup_task is None
