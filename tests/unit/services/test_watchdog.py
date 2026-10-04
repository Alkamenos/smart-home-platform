"""
Тесты сторожа: снимки состояний, обнаружение зависаний и потери связи.

Сторож переписан по решению D-1: раньше он не инстанцировался нигде, не имел
тестов и содержал два бага — обращение к несуществующему полю состояния и
``await`` синхронной функции, из-за чего цикл падал бы на первом же проходе.

Проверяется всё, что обещает FR-012…FR-018.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import CollectorRegistry
from src.core.events.event_bus import EventBus

from core.events.fsm_events import EVENT_PLATFORM_PROBLEM
from core.fsm.engine import FSMDefinition, FSMEngine, Transition
from core.metrics import MetricsCollector
from services.watchdog import FsmSnapshot, WatchdogService, WatchdogSettings


FSM_ID = "light.kitchen_lighting_10"
DEVICE = "light.kitchen"


class FakeClock:
    """Монотонные часы с управлением из теста.

    Стартовое значение — настоящее ``time.monotonic()``, чтобы совпадать с
    ``State.entered_at``, который движок заполняет монотонными часами.
    """

    def __init__(self, now: float | None = None) -> None:
        self.now = time.monotonic() if now is None else now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_definition(timeout_sec: float | None = 30.0) -> FSMDefinition:
    """Описание автомата с таймингованным переходом из начального состояния."""
    transitions = (
        Transition(
            from_state="on",
            to_state="standby",
            trigger="motion_cleared",
            timeout_sec=timeout_sec,
        ),
        Transition(from_state="standby", to_state="off", trigger="timeout"),
        Transition(from_state="off", to_state="on", trigger="motion_detected"),
    )
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="on",
        states=("on", "standby", "off"),
        transitions=transitions,
        target_device_id=DEVICE,
    )


@pytest.fixture
async def engine() -> FSMEngine:
    """Движок с одним зарегистрированным автоматом.

    Фикстура асинхронная намеренно: ``State.entered_at`` заполняется
    монотонными часами цикла, и вне работающего цикла движок записывает туда
    0.0 — против чего сравнивать время пребывания было бы бессмысленно.
    """
    engine = FSMEngine(event_bus=EventBus())
    engine.register_definition(make_definition(), restore_state=False)
    return engine


@pytest.fixture
def metrics() -> MetricsCollector:
    """Сборщик показателей с изолированным реестром."""
    collector = MetricsCollector(registry=CollectorRegistry())
    collector.initialize()
    return collector


def make_watchdog(
    engine: FSMEngine,
    metrics: MetricsCollector,
    adapter: Any | None = None,
    clock: FakeClock | None = None,
    event_bus: Any | None = None,
    **settings: Any,
) -> WatchdogService:
    """Собрать сторож с коротким интервалом для тестов."""
    return WatchdogService(
        fsm_engine=engine,
        metrics=metrics,
        adapter=adapter,
        settings=WatchdogSettings(interval_sec=0.01, **settings),
        clock=clock or FakeClock(),
        event_bus=event_bus,
    )


def _no_task_creation(coroutine: Any, *_args: Any, **_kwargs: Any) -> Any:
    """Отказать в создании задачи, закрыв корутину, чтобы она не текла.

    Args:
        coroutine: Корутина, которую сторож хочет запустить задачей.
        *_args: Прочие позиционные аргументы create_task.
        **_kwargs: Прочие именованные аргументы create_task.

    Raises:
        RuntimeError: Всегда — задачу создать не удалось.
    """
    coroutine.close()
    raise RuntimeError("no running event loop")


class TestSnapshot:
    """Снимок состояний (FR-012)."""

    async def test_should_use_state_name_when_snapshot_taken(self, engine: FSMEngine) -> None:
        """В снимок попадает имя состояния, а не текстовое представление объекта.

        Прежний код искал поля ``current``/``state``, которых у ``State`` нет, и
        писал в снимок ``repr`` дата-класса.
        """
        watchdog = make_watchdog(engine, MetricsCollector(registry=CollectorRegistry()))

        snapshot = await watchdog.check_once()

        assert isinstance(snapshot, FsmSnapshot)
        assert snapshot.entries[0].state == "on"
        assert "FsmSnapshotEntry" not in snapshot.entries[0].state

    async def test_should_report_device_from_definition_in_snapshot(
        self, engine: FSMEngine
    ) -> None:
        """Устройство в снимке берётся из описания автомата."""
        watchdog = make_watchdog(engine, MetricsCollector(registry=CollectorRegistry()))

        snapshot = await watchdog.check_once()

        assert snapshot.entries[0].device == DEVICE

    async def test_should_include_last_transition_time_when_snapshot_taken(
        self, engine: FSMEngine
    ) -> None:
        """Время последнего перехода берётся у движка, а не выдумывается."""
        watchdog = make_watchdog(engine, MetricsCollector(registry=CollectorRegistry()))

        snapshot = await watchdog.check_once()

        assert snapshot.entries[0].last_transition is None
        before = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        engine.note_transition(FSM_ID)
        snapshot = await watchdog.check_once()
        recorded = snapshot.entries[0].last_transition
        assert recorded is not None
        # Время приходит настенное и в формате интерфейса, а не монотонное.
        assert recorded.startswith(before)

    async def test_should_report_empty_snapshot_when_no_automats(self) -> None:
        """Отсутствие автоматов — пустой снимок, а не ошибка."""
        watchdog = make_watchdog(
            FSMEngine(event_bus=EventBus()), MetricsCollector(registry=CollectorRegistry())
        )

        snapshot = await watchdog.check_once()

        assert not snapshot.entries
        assert snapshot.problem_count == 0

    async def test_should_return_snapshot_when_check_fails(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Сбой проверки возвращает пустой снимок и пишет в журнал."""
        watchdog = make_watchdog(engine, metrics)

        with (
            patch.object(engine, "get_all_states", side_effect=RuntimeError("boom")),
            patch("services.watchdog.logger") as mock_logger,
        ):
            snapshot = await watchdog.check_once()

        assert not snapshot.entries
        assert mock_logger.warning.called


class TestStuckDetection:
    """Обнаружение зависших автоматов (FR-013)."""

    async def test_should_mark_stuck_when_state_held_beyond_expectation(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Пребывание дольше ожидаемого времени плюс запас — зависание."""
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock, stuck_grace_sec=10)

        clock.advance(31)
        assert (await watchdog.check_once()).entries[0].stuck is False

        clock.advance(10)
        assert (await watchdog.check_once()).entries[0].stuck is True

    async def test_should_not_mark_stuck_when_state_has_no_timeout(
        self, metrics: MetricsCollector
    ) -> None:
        """Состояние без таймингованных переходов зависшим не считается.

        Оно живёт, пока не придёт событие; называть его зависшим значило бы
        ложно срабатывать на ночном свете и режимах длиной в сутки.
        """
        engine = FSMEngine(event_bus=EventBus())
        engine.register_definition(make_definition(timeout_sec=None), restore_state=False)
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock)

        clock.advance(100_000)
        snapshot = await watchdog.check_once()

        assert snapshot.entries[0].expected_timeout_sec is None
        assert snapshot.entries[0].stuck is False

    async def should_report_expected_timeout_in_snapshot(self, engine: FSMEngine) -> None:
        """Снимок содержит ожидаемое время пребывания для диагностики."""
        watchdog = make_watchdog(engine, MetricsCollector(registry=CollectorRegistry()))

        snapshot = await watchdog.check_once()

        assert snapshot.entries[0].expected_timeout_sec == 30.0


class TestConnectionLoss:
    """Потеря связи с внешней системой (FR-014)."""

    async def test_should_report_lost_when_adapter_disconnected_beyond_threshold(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Отсутствие связи дольше порога — проблема."""
        adapter = MagicMock()
        adapter.connected = False
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, adapter=adapter, clock=clock, ha_loss_sec=100)

        clock.advance(50)
        assert (await watchdog.check_once()).ha_disconnected is False

        # Отсчёт потери начинается с первой проверки без связи, поэтому
        # порог отсчитывается от неё, а не от последнего успеха.
        clock.advance(120)
        assert (await watchdog.check_once()).ha_disconnected is True

    async def should_not_report_lost_when_adapter_reconnected(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Восстановление связи снимает проблему (FR-016)."""
        adapter = MagicMock()
        adapter.connected = False
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, adapter=adapter, clock=clock, ha_loss_sec=100)

        clock.advance(200)
        assert (await watchdog.check_once()).ha_disconnected is True

        adapter.connected = True
        assert (await watchdog.check_once()).ha_disconnected is False

    async def test_should_not_report_lost_when_no_external_system(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """В автономном режиме внешней системы нет, и это не проблема."""
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, adapter=None, clock=clock, ha_loss_sec=10)

        clock.advance(100_000)
        snapshot = await watchdog.check_once()

        assert snapshot.ha_disconnected is False
        assert snapshot.ha_checked is False

    async def test_should_not_report_lost_when_connection_healthy(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Штатное состояние связи не считается проблемой."""
        adapter = MagicMock()
        adapter.connected = True
        watchdog = make_watchdog(engine, metrics, adapter=adapter, ha_loss_sec=10)

        snapshot = await watchdog.check_once()

        assert snapshot.ha_disconnected is False
        assert snapshot.ha_checked is True


class TestProblemPublication:
    """События проблем (FR-015, FR-016)."""

    async def test_should_publish_problem_once_when_stuck_detected(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Повторные проверки зависшего автомата новых событий не порождают."""
        bus = MagicMock()
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock, stuck_grace_sec=5, event_bus=bus)
        clock.advance(100)

        await watchdog.check_once()
        await watchdog.check_once()
        await watchdog.check_once()

        published = [
            call for call in bus.publish.call_args_list if call[0][0] == EVENT_PLATFORM_PROBLEM
        ]
        assert len(published) == 1
        payload = published[0][0][1]
        assert payload["kind"] == "fsm_stuck"
        assert payload["entity_id"] == FSM_ID
        assert payload["resolved"] is False

    async def test_should_publish_resolution_with_duration_when_fixed(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Устранение проблемы публикуется один раз и с длительностью."""
        bus = MagicMock()
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock, stuck_grace_sec=5, event_bus=bus)
        clock.advance(100)
        await watchdog.check_once()

        engine.reset_state(FSM_ID, "off")
        await watchdog.check_once()

        published = [
            call for call in bus.publish.call_args_list if call[0][0] == EVENT_PLATFORM_PROBLEM
        ]
        assert len(published) == 2
        resolution = published[-1][0][1]
        assert resolution["resolved"] is True
        assert resolution["duration_sec"] is not None
        assert resolution["resolved_at"] is not None

    async def should_not_publish_when_nothing_wrong(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Штатная проверка не публикует событий."""
        bus = MagicMock()
        watchdog = make_watchdog(engine, metrics, event_bus=bus)

        await watchdog.check_once()

        assert not [
            call for call in bus.publish.call_args_list if call[0][0] == EVENT_PLATFORM_PROBLEM
        ]


class TestWatchdogMetrics:
    """Показатели сторожа (FR-015, SC-010)."""

    async def test_should_count_checks_and_stuck_in_metrics(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Результат проверки и зависание попадают в показатели."""
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock, stuck_grace_sec=5)
        clock.advance(100)

        snapshot = await watchdog.check_once()

        assert snapshot.result == "degraded"
        assert (
            metrics.registry.get_sample_value("watchdog_checks_total", {"result": "degraded"}) == 1
        )
        assert metrics.registry.get_sample_value("fsm_stuck_current", {"fsm_name": FSM_ID}) == 1

    async def should_reset_stuck_gauge_when_resolved(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """После устранения зависания шкала возвращается к нулю."""
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, clock=clock, stuck_grace_sec=5)
        clock.advance(100)
        await watchdog.check_once()

        engine.reset_state(FSM_ID, "off")
        await watchdog.check_once()

        assert metrics.registry.get_sample_value("fsm_stuck_current", {"fsm_name": FSM_ID}) == 0

    async def test_should_set_connection_lost_gauge_when_link_down(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Потеря связи отражается в шкале, а не только в журнале."""
        adapter = MagicMock()
        adapter.connected = False
        clock = FakeClock()
        watchdog = make_watchdog(engine, metrics, adapter=adapter, clock=clock, ha_loss_sec=10)

        await watchdog.check_once()
        clock.advance(100)
        await watchdog.check_once()

        assert metrics.registry.get_sample_value("ha_connection_lost", {}) == 1

    async def should_count_failed_check_when_reading_fails(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Сбой проверки учитывается отдельным результатом."""
        watchdog = make_watchdog(engine, metrics)
        with patch.object(engine, "get_all_states", side_effect=RuntimeError("boom")):
            await watchdog.check_once()

        assert metrics.registry.get_sample_value("watchdog_checks_total", {"result": "failed"}) == 1


class TestWatchdogLifecycle:
    """Жизненный цикл сторожа (FR-017, FR-018)."""

    async def test_should_run_checks_when_started(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Запущенный сторож выполняет проверки."""
        watchdog = make_watchdog(engine, metrics)

        watchdog.start()
        await asyncio.sleep(0.05)
        await watchdog.stop()

        checks = metrics.registry.get_sample_value("watchdog_checks_total", {"result": "ok"})
        assert checks is not None and checks >= 1

    async def test_leave_no_pending_tasks_when_stopped(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """После остановки не остаётся висящих задач."""
        watchdog = make_watchdog(engine, metrics)
        before = len(asyncio.all_tasks())

        watchdog.start()
        await asyncio.sleep(0.03)
        await watchdog.stop()

        await asyncio.sleep(0)
        assert len(asyncio.all_tasks()) <= before

    async def should_be_idempotent_when_started_twice(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Повторный запуск не создаёт второй цикл."""
        watchdog = make_watchdog(engine, metrics)

        watchdog.start()
        task = watchdog._task
        watchdog.start()

        assert watchdog._task is task
        await watchdog.stop()

    async def test_should_not_raise_when_stopped_without_start(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Остановка без запуска безопасна и снимает отметку о запуске (FR-017)."""
        watchdog = make_watchdog(engine, metrics)
        tasks_before = len(asyncio.all_tasks())

        await watchdog.stop()
        await watchdog.stop()

        assert watchdog._running is False
        assert watchdog._task is None
        assert len(asyncio.all_tasks()) == tasks_before, "stop() не должен запускать задач"
        assert metrics.registry.get_sample_value("watchdog_checks_total", {"result": "ok"}) is None

        # Сторож помечается запущенным до создания задачи, поэтому сбой создания
        # задачи оставляет его «запущенным» без задачи. stop() обязан снять эту
        # отметку, иначе сторож не запустится больше никогда.
        with (
            patch.object(asyncio, "create_task", side_effect=_no_task_creation),
            pytest.raises(RuntimeError),
        ):
            watchdog.start()
        assert watchdog._running is True, "start() помечает сторожа запущенным до создания задачи"

        await watchdog.stop()

        assert watchdog._running is False
        assert watchdog._task is None

        watchdog.start()
        await asyncio.sleep(0.05)
        await watchdog.stop()

        checks = metrics.registry.get_sample_value("watchdog_checks_total", {"result": "ok"})
        assert checks is not None and checks >= 1, "после досрочной остановки сторож запускается"

    async def test_should_survive_check_failure_in_loop(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Сбой одной проверки не прерывает цикл (FR-018)."""
        watchdog = make_watchdog(engine, metrics)
        calls = {"count": 0}
        original = engine.get_all_states

        def flaky() -> dict[str, Any]:
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("boom")
            return original()

        with patch.object(engine, "get_all_states", side_effect=flaky):
            watchdog.start()
            await asyncio.sleep(0.08)
            await watchdog.stop()

        assert calls["count"] >= 2, "loop stopped after the first failure"

    async def should_keep_checking_after_disabling(
        self, engine: FSMEngine, metrics: MetricsCollector
    ) -> None:
        """Остановленный сторож больше не проверяет."""
        watchdog = make_watchdog(engine, metrics)
        watchdog.start()
        await watchdog.stop()
        before = metrics.registry.get_sample_value("watchdog_checks_total", {"result": "ok"})

        await asyncio.sleep(0.05)

        assert (
            metrics.registry.get_sample_value("watchdog_checks_total", {"result": "ok"}) == before
        )
