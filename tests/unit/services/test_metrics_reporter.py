"""
Тесты подписчика показателей (FR-003, FR-004, FR-008).

Подписчик ``MetricsReporter`` переводит уже публикуемые события перехода,
отказа и восстановления в показатели. Движок при этом не трогается: он не
должен зависеть от наличия коллектора (конституция I, FR-001).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry
from src.core.events.event_bus import EventBus

from core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_RESTORED,
    EVENT_FSM_TRANSITIONED,
    OUTCOME_REJECTED,
    OUTCOME_TRANSITIONED,
    REASON_DEBOUNCED,
    build_transition_payload,
)
from core.metrics import MetricsCollector
from services.metrics_reporter import MetricsReporter


FSM_ID = "light.kitchen_lighting_10"
DEVICE = "light.kitchen"


@pytest.fixture
def registry() -> CollectorRegistry:
    """Изолированный реестр измерений на тест."""
    return CollectorRegistry()


@pytest.fixture
def metrics(registry: CollectorRegistry) -> MetricsCollector:
    """Инициализированный сборщик показателей."""
    collector = MetricsCollector(registry=registry)
    collector.initialize()
    return collector


@pytest.fixture
def bus() -> EventBus:
    """Шина событий платформы."""
    return EventBus()


@pytest.fixture
def reporter(bus: EventBus, metrics: MetricsCollector) -> MetricsReporter:
    """Подписчик показателей, подключённый к шине."""
    reporter = MetricsReporter(bus, metrics)
    return reporter


def transition_payload(**overrides: Any) -> dict[str, Any]:
    """Полезная нагрузка выполненного перехода."""
    payload = build_transition_payload(
        fsm_id=FSM_ID,
        device_id=DEVICE,
        from_state="off",
        to_state="on",
        event="motion_detected",
        outcome=OUTCOME_TRANSITIONED,
        trace_id="trace-1",
    )
    payload.update(overrides)
    return payload


def rejection_payload(reason: str = REASON_DEBOUNCED) -> dict[str, Any]:
    """Полезная нагрузка отклонённого перехода."""
    return build_transition_payload(
        fsm_id=FSM_ID,
        device_id=DEVICE,
        from_state="on",
        to_state=None,
        event="motion_detected",
        outcome=OUTCOME_REJECTED,
        trace_id="trace-2",
        reason=reason,
    )


class TestMetricsReporterTransition:
    """Учёт выполненных переходов."""

    async def test_should_increment_transitions_when_transitioned(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Переход увеличивает счётчик ровно на 1 с полным набором меток."""
        await reporter.handle(EVENT_FSM_TRANSITIONED, transition_payload())

        assert (
            registry.get_sample_value(
                "fsm_transitions_total",
                {
                    "fsm_name": FSM_ID,
                    "from_state": "off",
                    "to_state": "on",
                    "device": DEVICE,
                },
            )
            == 1
        )

    async def test_should_use_device_from_payload_when_fsm_id_ambiguous(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Устройство берётся из полезной нагрузки, а не разбирается из имени.

        Разбор идентификатора по ``_`` даёт коллизию префиксов (Known Issue
        #20), поэтому метка устройства берётся как есть.
        """
        await reporter.handle(EVENT_FSM_TRANSITIONED, transition_payload())

        labels = {
            tuple(sample.labels.values())[-1]
            for metric in registry.collect()
            if metric.name == "fsm_transitions"
            for sample in metric.samples
            if sample.name == "fsm_transitions_total"
        }
        assert DEVICE in labels

    async def test_should_ignore_transition_when_collector_not_initialized(
        self, bus: EventBus, registry: CollectorRegistry
    ) -> None:
        """Неинициализированный сборщик не приводит к исключению."""
        reporter = MetricsReporter(bus, MetricsCollector(registry=registry))

        await reporter.handle(EVENT_FSM_TRANSITIONED, transition_payload())


class TestMetricsReporterRejection:
    """Учёт отклонённых переходов."""

    async def test_should_increment_rejections_with_reason_when_rejected(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Отказ учитывается отдельно, с причиной."""
        await reporter.handle(EVENT_FSM_REJECTED, rejection_payload())

        assert (
            registry.get_sample_value(
                "fsm_rejections_total",
                {"fsm_name": FSM_ID, "reason": REASON_DEBOUNCED},
            )
            == 1
        )

    async def test_should_not_increment_transitions_when_rejected(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Отказ не должен выглядеть как выполненный переход (FR-004)."""
        await reporter.handle(EVENT_FSM_REJECTED, rejection_payload())

        transitions = [
            sample
            for metric in registry.collect()
            if metric.name == "fsm_transitions"
            for sample in metric.samples
            if sample.name == "fsm_transitions_total"
        ]
        assert transitions == []

    async def test_should_count_each_rejection_reason_separately(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Разные причины дают разные серии, одна причина — один счётчик."""
        await reporter.handle(EVENT_FSM_REJECTED, rejection_payload(REASON_DEBOUNCED))
        await reporter.handle(EVENT_FSM_REJECTED, rejection_payload("no_transition"))

        assert (
            registry.get_sample_value(
                "fsm_rejections_total", {"fsm_name": FSM_ID, "reason": REASON_DEBOUNCED}
            )
            == 1
        )
        assert (
            registry.get_sample_value(
                "fsm_rejections_total", {"fsm_name": FSM_ID, "reason": "no_transition"}
            )
            == 1
        )


class TestMetricsReporterRestored:
    """Учёт восстановлений состояний."""

    async def test_should_increment_restored_when_state_restored(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Восстановление состояния после перезапуска попадает в показатели."""
        await reporter.handle(EVENT_FSM_RESTORED, {"fsm_id": FSM_ID, "state": "on"})

        assert registry.get_sample_value("fsm_states_restored_total", {"fsm_name": FSM_ID}) == 1


class TestMetricsReporterResilience:
    """Устойчивость подписчика."""

    async def test_should_ignore_event_when_type_unknown(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Неизвестный тип события не приводит к записи."""
        await reporter.handle("platform.started", {"manifest": "x"})

        assert registry.get_sample_value("fsm_transitions_total", {}) is None

    async def test_should_log_and_continue_when_payload_incomplete(
        self, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Неполная полезная нагрузка фиксируется в журнале, но не роняет обработку."""
        with patch("services.metrics_reporter.logger") as mock_logger:
            await reporter.handle(EVENT_FSM_TRANSITIONED, {"fsm_id": FSM_ID})

        assert mock_logger.warning.called

    async def test_should_not_raise_when_collector_fails(
        self, bus: EventBus, registry: CollectorRegistry
    ) -> None:
        """Ошибка записи в показатели не прерывает обработку события (FR-008)."""
        metrics = MagicMock(spec=MetricsCollector)
        metrics.is_initialized.return_value = True
        metrics.record_fsm_transition.side_effect = RuntimeError("boom")
        reporter = MetricsReporter(bus, metrics)

        await reporter.handle(EVENT_FSM_TRANSITIONED, transition_payload())


class TestMetricsReporterSubscriptions:
    """Подписка на шину платформы."""

    def test_should_subscribe_to_transition_events_when_created(self, bus: EventBus) -> None:
        """Подписчик обязан слушать все три события состояний."""
        MetricsReporter(bus, MetricsCollector())

        assert EVENT_FSM_TRANSITIONED in bus._subscribers
        assert EVENT_FSM_REJECTED in bus._subscribers
        assert EVENT_FSM_RESTORED in bus._subscribers

    async def test_should_record_when_event_published_to_bus(
        self, bus: EventBus, reporter: MetricsReporter, registry: CollectorRegistry
    ) -> None:
        """Путь «переход → шина → показатель» работает end-to-end."""
        await bus.publish(EVENT_FSM_TRANSITIONED, transition_payload())

        assert (
            registry.get_sample_value(
                "fsm_transitions_total",
                {
                    "fsm_name": FSM_ID,
                    "from_state": "off",
                    "to_state": "on",
                    "device": DEVICE,
                },
            )
            == 1
        )
