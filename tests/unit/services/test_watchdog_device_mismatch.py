"""Сторож обязан видеть расхождение «автомат ↔ прибор» (концепция §7, п. 4).

Решение может быть «выключено», а прибор гореть: команда не применилась,
прибор недоступен, кто-то включил свет мимо платформы. Без сверки такое
расхождение невидимо, и утренний разбор не отличает «не мог» от «сделал».
Боевой повод — 2026-10-14: на рассвете автомат ночного освещения ушёл в `OFF`,
а три уличные лампы остались гореть (одна — с 12 октября).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from prometheus_client import CollectorRegistry

from core.events.event_bus import EventBus
from core.events.fsm_events import EVENT_PLATFORM_PROBLEM, PROBLEM_DEVICE_MISMATCH
from core.metrics import MetricsCollector
from services.watchdog import (
    DEVICE_DIVERGED_TRIGGER,
    DIVERGENCE_REASSERT_ATTEMPTS,
    MISMATCH_DEVICE_OFF_DECISION_ON,
    MISMATCH_DEVICE_ON_DECISION_OFF,
    MISMATCH_DEVICE_UNAVAILABLE,
    MISMATCH_MANUAL_OVERRIDE,
    WatchdogService,
    WatchdogSettings,
)


FSM_ID = "light.group_nochnoe_osveshcheni_deco_light_10"
DEVICE = "light.group_nochnoe_osveshcheni"
COVER_FSM = "cover.shtora_v_kabinet_cover_modes_10"
COVER_DEVICE = "cover.shtora_v_kabinet"


@dataclass
class FakeEngine:
    """Движок ровно с тем, что спрашивает сторож.

    Attributes:
        states: Автомат → текущее состояние.
        devices: Автомат → сущность прибора.
        outcomes: Автомат → исход последнего решения («on»/«off»/``None``).
    """

    states: dict[str, str]
    devices: dict[str, str]
    outcomes: dict[str, str | None] = field(default_factory=dict)
    #: Записанные повторы решения: (автомат, событие, respect_debounce).
    triggered: list[tuple[str, str, bool]] = field(default_factory=list)

    async def trigger(
        self,
        entity_id: str,
        event: str,
        external_ctx: dict[str, Any] | None = None,
        respect_debounce: bool = True,
        trace_id: str | None = None,
    ) -> bool:
        """Запомнить повтор решения.

        Args:
            entity_id: Автомат.
            event: Событие.
            external_ctx: Внешний контекст (не используется).
            respect_debounce: Флаг дебаунса.
            trace_id: Идентификатор трассы (не используется).

        Returns:
            True — повтор принят.
        """
        self.triggered.append((entity_id, event, respect_debounce))
        return True

    def get_all_states(self) -> dict[str, Any]:
        """Состояния всех автоматов."""
        now = time.monotonic()
        return {
            entity_id: SimpleNamespace(current_state=state, entered_at=now, context={})
            for entity_id, state in self.states.items()
        }

    def expected_timeout_sec(self, entity_id: str) -> float | None:
        """Зависание не проверяется: оно не предмет этого теста."""
        return None

    def device_id_of(self, entity_id: str) -> str | None:
        """Сущность прибора автомата."""
        return self.devices.get(entity_id)

    def get_last_transition_time(self, entity_id: str) -> str | None:
        """Время последнего перехода неизвестно."""
        return None

    def explain(self, entity_id: str) -> Any | None:
        """Последнее решение автомата."""
        outcome = self.outcomes.get(entity_id)
        if outcome is None:
            return None
        return SimpleNamespace(outcome=outcome)


@dataclass
class FakeAdapter:
    """Внешняя система: состояния приборов задаются тестом.

    Attributes:
        device_states: Сущность → состояние; ``None`` — прибор не ответил.
        fail: Бросать ли ошибку на чтении.
    """

    device_states: dict[str, str | None] = field(default_factory=dict)
    fail: bool = False

    is_connected = True

    async def get_entity_state(self, entity_id: str) -> str | None:
        """Прочитать состояние прибора."""
        if self.fail:
            raise RuntimeError("связь потеряна")
        return self.device_states.get(entity_id)


def make_watchdog(
    engine: FakeEngine,
    adapter: Any | None = None,
    event_bus: Any | None = None,
    manual_override: Any | None = None,
) -> WatchdogService:
    """Собрать сторож с подменёнными движком и внешней системой.

    Args:
        engine: Движок-двойник.
        adapter: Внешняя система-двойник.
        event_bus: Шина событий для проверки публикации проблем.
        manual_override: Признак действующей ручной блокировки.

    Returns:
        Сторож.
    """
    return WatchdogService(
        fsm_engine=engine,  # type: ignore[arg-type]
        metrics=MetricsCollector(registry=CollectorRegistry()),
        adapter=adapter,  # type: ignore[arg-type]
        settings=WatchdogSettings(interval_sec=0.01),
        event_bus=event_bus,
        manual_override_supplier=manual_override,
    )


class Collector:
    """Подписчик шины, собирающий события о проблемах."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event_type: str, payload: dict[str, Any], trace_id: str = "") -> None:
        """Запомнить событие."""
        self.events.append(dict(payload))


@pytest.mark.asyncio
async def test_decision_off_device_on_is_a_mismatch() -> None:
    """Решение «выключено», прибор горит — расхождение названо."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    entry = snapshot.entries[0]
    assert entry.device_state == "on"
    assert entry.mismatch_reason == MISMATCH_DEVICE_ON_DECISION_OFF
    assert entry.mismatch is True
    assert snapshot.problem_count == 1


@pytest.mark.asyncio
async def test_decision_on_device_off_is_a_mismatch() -> None:
    """Решение «включить», прибор не горит — расхождение названо."""
    engine = FakeEngine({FSM_ID: "ON_MOTION"}, {FSM_ID: DEVICE}, {FSM_ID: "on"})
    adapter = FakeAdapter({DEVICE: "off"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].mismatch_reason == MISMATCH_DEVICE_OFF_DECISION_ON


@pytest.mark.asyncio
async def test_matching_device_is_not_a_problem() -> None:
    """Прибор согласен с решением — проблемы нет."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "off"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].device_state == "off"
    assert snapshot.entries[0].mismatch is False
    assert snapshot.problem_count == 0


@pytest.mark.asyncio
async def test_unavailable_device_is_named() -> None:
    """Недоступный прибор — отдельное наблюдаемое состояние, а не молчание."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "unavailable"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].mismatch_reason == MISMATCH_DEVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_read_failure_is_not_a_mismatch() -> None:
    """Сбой чтения — не приговор решению: расхождение не выдумывается."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter(fail=True)

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].device_state is None
    assert snapshot.entries[0].mismatch is False


@pytest.mark.asyncio
async def test_silent_device_is_not_a_mismatch() -> None:
    """Прибор не ответил (``None``) — это молчание, а не расхождение."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: None})

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].mismatch is False


@pytest.mark.asyncio
async def test_cover_is_compared_by_position() -> None:
    """Штора сверяется по положению: `OPEN` ждёт `open`, а не `on`."""
    engine = FakeEngine({COVER_FSM: "OPEN"}, {COVER_FSM: COVER_DEVICE})
    watchdog = make_watchdog(engine, FakeAdapter({COVER_DEVICE: "open"}))
    assert (await watchdog.check_once()).entries[0].mismatch is False

    closed = make_watchdog(engine, FakeAdapter({COVER_DEVICE: "closed"}))
    assert (await closed.check_once()).entries[0].mismatch_reason == MISMATCH_DEVICE_OFF_DECISION_ON


@pytest.mark.asyncio
async def test_unknown_state_is_not_guessed() -> None:
    """Незнакомое состояние автомата не превращается в догадку."""
    engine = FakeEngine({FSM_ID: "НЕЧТО"}, {FSM_ID: DEVICE})
    adapter = FakeAdapter({DEVICE: "on"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    assert snapshot.entries[0].device_state is None
    assert snapshot.entries[0].mismatch is False


@pytest.mark.asyncio
async def test_problem_is_published_once_and_resolved() -> None:
    """Проблема публикуется при появлении и устранении, а не каждый цикл."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})
    bus = EventBus()
    collector = Collector()
    bus.subscribe(EVENT_PLATFORM_PROBLEM, collector)
    watchdog = make_watchdog(engine, adapter, event_bus=bus)

    await watchdog.check_once()
    await watchdog._drain_publish_tasks()
    await watchdog.check_once()
    await watchdog._drain_publish_tasks()
    assert [event["kind"] for event in collector.events] == [PROBLEM_DEVICE_MISMATCH]
    assert collector.events[0]["resolved"] is False

    adapter.device_states[DEVICE] = "off"
    await watchdog.check_once()
    await watchdog._drain_publish_tasks()
    assert collector.events[-1]["kind"] == PROBLEM_DEVICE_MISMATCH
    assert collector.events[-1]["resolved"] is True


@pytest.mark.asyncio
async def test_manual_override_is_not_a_fault() -> None:
    """Расхождение из-за ручного вмешательства — уступка, а не отказ."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})
    bus = EventBus()
    collector = Collector()
    bus.subscribe(EVENT_PLATFORM_PROBLEM, collector)

    snapshot = await make_watchdog(
        engine, adapter, event_bus=bus, manual_override=lambda device: True
    ).check_once()
    await make_watchdog(engine, adapter).check_once()

    entry = snapshot.entries[0]
    assert entry.mismatch is True
    assert entry.mismatch_reason == MISMATCH_MANUAL_OVERRIDE
    assert entry.mismatch_is_fault is False
    assert snapshot.problem_count == 0
    assert collector.events == []


@pytest.mark.asyncio
async def test_manual_override_supplier_failure_is_not_a_fault() -> None:
    """Сбой проверки блокировки не превращается в уступку человеку."""

    def broken(device: str) -> bool:
        """Проверка блокировки, которая падает."""
        raise RuntimeError("трекер недоступен")

    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})

    snapshot = await make_watchdog(engine, adapter, manual_override=broken).check_once()

    assert snapshot.entries[0].mismatch_reason == MISMATCH_DEVICE_ON_DECISION_OFF
    assert snapshot.problem_count == 1


@pytest.mark.asyncio
async def test_divergence_repeats_the_decision() -> None:
    """Прибор разошёлся с решением — автомат просит повторить решение (B64)."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})

    await make_watchdog(engine, adapter).check_once()

    assert engine.triggered == [(FSM_ID, DEVICE_DIVERGED_TRIGGER, False)]


@pytest.mark.asyncio
async def test_divergence_repeats_are_bounded() -> None:
    """Неотвечающий прибор не получает команду каждый цикл сторожа."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})
    watchdog = make_watchdog(engine, adapter)

    for _ in range(DIVERGENCE_REASSERT_ATTEMPTS + 2):
        await watchdog.check_once()

    assert len(engine.triggered) == DIVERGENCE_REASSERT_ATTEMPTS


@pytest.mark.asyncio
async def test_divergence_counter_resets_when_device_agrees() -> None:
    """Прибор согласился — следующий отказ снова получает повторы."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})
    watchdog = make_watchdog(engine, adapter)

    for _ in range(DIVERGENCE_REASSERT_ATTEMPTS):
        await watchdog.check_once()
    adapter.device_states[DEVICE] = "off"
    await watchdog.check_once()
    adapter.device_states[DEVICE] = "on"
    await watchdog.check_once()

    assert len(engine.triggered) == DIVERGENCE_REASSERT_ATTEMPTS + 1


@pytest.mark.asyncio
async def test_manual_override_is_not_reasserted() -> None:
    """Уступку человеку повторять нельзя: автоматика уступает по правилу."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})

    await make_watchdog(engine, adapter, manual_override=lambda device: True).check_once()

    assert engine.triggered == []


@pytest.mark.asyncio
async def test_snapshot_json_reports_device_state() -> None:
    """Снимок для журнала показывает и состояние прибора, и расхождение."""
    engine = FakeEngine({FSM_ID: "OFF"}, {FSM_ID: DEVICE}, {FSM_ID: "off"})
    adapter = FakeAdapter({DEVICE: "on"})

    snapshot = await make_watchdog(engine, adapter).check_once()

    payload = snapshot.to_json()
    assert '"device_state": "on"' in payload
    assert f'"mismatch": "{MISMATCH_DEVICE_ON_DECISION_OFF}"' in payload
