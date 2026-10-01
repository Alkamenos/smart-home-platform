"""
Тесты публикации переходов автомата в шину событий (FR-001…FR-011).

Проверяют контракт `contracts/fsm-events.md`: успешный переход публикует
`fsm.transitioned`, каждый отказ — `fsm.rejected` с причиной, признак источника
выводится из имени триггера.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from src.core.events.event_bus import EventBus
from src.core.events.fsm_events import (
    EVENT_FSM_REJECTED,
    EVENT_FSM_TRANSITIONED,
    REASON_DEBOUNCED,
    REASON_GUARD_FAILED,
    REASON_NO_STATE,
    REASON_NO_TRANSITION,
    REASON_UNKNOWN_ENTITY,
    TIMESTAMP_FORMAT,
)

from core import FSMDefinition, FSMEngine, Transition


FSM_ID = "light.kitchen_lighting_10"
DEVICE_ID = "light.kitchen"


async def flush(engine: FSMEngine) -> None:
    """Дождаться доставки запланированных событий перехода.

    Публикация неблокирующая (FR-014), поэтому тест должен явно дренировать
    задачи публикации перед проверкой доставки.

    Args:
        engine: Движок состояний, задачи которого ожидаются.
    """
    await engine._drain_publish_tasks()


@pytest.fixture
def bus() -> EventBus:
    """Шина событий без подписчиков."""
    return EventBus()


@pytest.fixture
def published(bus: EventBus) -> list[tuple[str, dict[str, Any]]]:
    """Список опубликованных событий в порядке доставки."""
    events: list[tuple[str, dict[str, Any]]] = []

    async def collector(
        event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        events.append((event_type, payload))

    bus.subscribe(EVENT_FSM_TRANSITIONED, collector)
    bus.subscribe(EVENT_FSM_REJECTED, collector)
    return events


@pytest.fixture
def engine(bus: EventBus) -> FSMEngine:
    """Движок состояний, подключённый к шине."""
    return FSMEngine(event_bus=bus)


def make_definition(
    *,
    debounce_sec: float = 0.0,
    guard: Any = None,
    transitions: tuple[Transition, ...] | None = None,
) -> FSMDefinition:
    """Собрать описание автомата освещения кухни.

    Args:
        debounce_sec: Защита от дребезга в секундах.
        guard: Условие перехода.
        transitions: Переходы; по умолчанию — одиночный `motion_detected`.

    Returns:
        Описание автомата для регистрации в движке.
    """
    return FSMDefinition(
        entity_id=FSM_ID,
        initial_state="OFF",
        states=("OFF", "ON_MOTION"),
        transitions=transitions
        or (
            Transition(
                from_state="OFF",
                to_state="ON_MOTION",
                trigger="motion_detected",
                guard=guard,
            ),
        ),
        debounce_sec=debounce_sec,
        target_device_id=DEVICE_ID,
    )


class TestSuccessfulTransition:
    """Выполненный переход публикует fsm.transitioned (FR-001, FR-002)."""

    async def test_should_publish_transitioned_when_transition_occurs(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Переход публикует одно событие типа fsm.transitioned."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert [event_type for event_type, _ in published] == [EVENT_FSM_TRANSITIONED]

    async def test_should_include_all_required_fields_when_transition_occurs(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Полезная нагрузка содержит полный набор полей контракта."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected", trace_id="abc12345")
        await flush(engine)

        payload = published[0][1]
        assert payload["fsm_id"] == FSM_ID
        assert payload["device_id"] == DEVICE_ID
        assert payload["behavior"] == "lighting"
        assert payload["from_state"] == "OFF"
        assert payload["to_state"] == "ON_MOTION"
        assert payload["event"] == "motion_detected"
        assert payload["source"] == "automatic"
        assert payload["outcome"] == "transitioned"
        assert payload["trace_id"] == "abc12345"
        assert payload["reason"] is None

    async def test_should_use_nanosecond_free_iso_timestamp_when_transition_occurs(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Время перехода — настенное ISO-8601, разбираемое datetime."""
        from datetime import datetime

        from src.core.events.fsm_events import TIMESTAMP_FORMAT

        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        timestamp = published[0][1]["timestamp"]
        assert isinstance(timestamp, str)
        assert datetime.strptime(timestamp, TIMESTAMP_FORMAT)

    async def test_should_publish_after_state_is_written_when_subscribed(
        self, engine: FSMEngine, bus: EventBus
    ) -> None:
        """Подписчик, читающий состояние движка, видит уже новое состояние."""
        observed: list[str] = []

        async def observer(
            event_type: str, payload: dict[str, Any], trace_id: str | None = None
        ) -> None:
            state = engine.get_state(FSM_ID)
            observed.append(state.current_state if state else "")

        bus.subscribe(EVENT_FSM_TRANSITIONED, observer)
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert observed == ["ON_MOTION"]


class TestRejectedTransitions:
    """Отказ публикует fsm.rejected с причиной (FR-004)."""

    async def test_should_publish_rejected_when_entity_unknown(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Неизвестный автомат — отказ с причиной unknown_entity."""
        await engine.trigger("light.absent_lighting_10", "motion_detected")
        await flush(engine)

        assert len(published) == 1
        event_type, payload = published[0]
        assert event_type == EVENT_FSM_REJECTED
        assert payload["reason"] == REASON_UNKNOWN_ENTITY
        assert payload["outcome"] == "rejected"
        assert payload["to_state"] is None

    async def test_should_publish_rejected_when_state_missing(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Описание без состояния — отказ с причиной no_state."""
        engine._states.clear()
        engine.register_definition(make_definition())
        engine._states.pop(FSM_ID)

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert published[0][1]["reason"] == REASON_NO_STATE

    async def test_should_publish_rejected_when_debounced(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Срабатывание защиты от дребезга — отказ с причиной debounced."""
        engine.register_definition(make_definition(debounce_sec=60.0))

        await engine.trigger(FSM_ID, "motion_detected")
        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        reasons = [
            payload["reason"]
            for event_type, payload in published
            if event_type == EVENT_FSM_REJECTED
        ]
        assert REASON_DEBOUNCED in reasons

    async def test_should_publish_rejected_when_no_transition_matches(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Событие без перехода из текущего состояния — отказ no_transition."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "unknown_event")
        await flush(engine)

        assert published[0][1]["reason"] == REASON_NO_TRANSITION

    async def test_should_publish_rejected_when_guard_fails(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Невыполненное условие перехода — отказ guard_failed."""

        def deny(state: Any, context: dict[str, Any]) -> bool:
            return False

        engine.register_definition(make_definition(guard=deny))

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert published[0][1]["reason"] == REASON_GUARD_FAILED

    async def test_should_not_publish_transitioned_when_transition_rejected(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Отказ не порождает события выполненного перехода."""
        engine.register_definition(make_definition(guard=lambda state, context: False))

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert EVENT_FSM_TRANSITIONED not in [event_type for event_type, _ in published]


class TestTransitionSource:
    """Источник перехода выводится из имени триггера (FR-002, FR-011)."""

    async def test_should_mark_source_manual_when_trigger_has_manual_prefix(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Событие manual_* помечается как ручное."""
        definition = make_definition(
            transitions=(
                Transition(from_state="OFF", to_state="ON_MOTION", trigger="manual_switch_on"),
            )
        )
        engine.register_definition(definition)

        await engine.trigger(FSM_ID, "manual_switch_on")
        await flush(engine)

        assert published[0][1]["source"] == "manual"

    async def test_should_mark_source_automatic_when_trigger_has_no_manual_prefix(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Обычное событие помечается как автоматическое."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        assert published[0][1]["source"] == "automatic"

    def test_should_classify_all_template_triggers_by_known_convention(self) -> None:
        """Все триггеры из шаблонов классифицируются по соглашению об именах."""
        from pathlib import Path

        from src.core.events.fsm_events import SOURCE_AUTOMATIC, SOURCE_MANUAL, classify_source

        features_dir = Path("src/features")
        triggers: set[str] = set()
        for yaml_file in features_dir.glob("*.yaml"):
            for line in yaml_file.read_text(encoding="utf-8").splitlines():
                if "trigger:" in line:
                    triggers.add(line.split("trigger:", 1)[1].strip())

        assert triggers, "в шаблонах не найдено ни одного триггера"
        for trigger in triggers:
            expected = SOURCE_MANUAL if trigger.startswith("manual_") else SOURCE_AUTOMATIC
            assert classify_source(trigger) == expected


class TestNoSpuriousEvents:
    """Повторный переход в то же состояние не порождает события (FR-009)."""

    async def test_should_not_publish_when_event_is_ignored_without_state_change(
        self, engine: FSMEngine, published: list[tuple[str, dict[str, Any]]]
    ) -> None:
        """Событие, не приводящее к переходу, не даёт события успеха."""
        engine.register_definition(make_definition())

        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)
        before = len(published)
        await engine.trigger(FSM_ID, "motion_detected")
        await flush(engine)

        success_count = sum(
            1 for event_type, _ in published if event_type == EVENT_FSM_TRANSITIONED
        )
        assert success_count == 1
        assert len(published) > before

    async def test_should_not_publish_when_engine_has_no_event_bus(self) -> None:
        """Без шины событий переход работает и не падает (FR-005, FR-016)."""
        engine = FSMEngine()
        engine.register_definition(make_definition())

        assert await engine.trigger(FSM_ID, "motion_detected") is True
        assert await engine.trigger("light.absent_lighting_10", "motion_detected") is False


class TestTransitionWallClock:
    """Движок фиксирует настенное время перехода (FR-017, R-04)."""

    async def test_should_return_transition_time_when_transition_occurs(
        self, engine: FSMEngine
    ) -> None:
        """После перехода доступно время перехода в настенном формате."""
        engine.register_definition(make_definition())

        assert engine.get_last_transition_time(FSM_ID) is None
        await engine.trigger(FSM_ID, "motion_detected")

        recorded = engine.get_last_transition_time(FSM_ID)
        assert recorded is not None
        assert datetime.strptime(recorded, TIMESTAMP_FORMAT)

    async def test_should_not_record_time_when_transition_rejected(self, engine: FSMEngine) -> None:
        """Отказ перехода не считается переходом, время не меняется."""
        engine.register_definition(make_definition())

        await engine.trigger("light.absent_lighting_10", "motion_detected")

        assert engine.get_last_transition_time("light.absent_lighting_10") is None

    async def test_should_clear_time_when_fsm_unregistered(self, engine: FSMEngine) -> None:
        """Снятый автомат не оставляет времени перехода."""
        engine.register_definition(make_definition())
        await engine.trigger(FSM_ID, "motion_detected")

        engine.unregister(FSM_ID)

        assert engine.get_last_transition_time(FSM_ID) is None

    async def test_should_keep_time_when_state_reset(self, engine: FSMEngine) -> None:
        """Сброс состояния не является переходом, поэтому время прежнее."""
        engine.register_definition(make_definition())
        await engine.trigger(FSM_ID, "motion_detected")
        recorded = engine.get_last_transition_time(FSM_ID)

        engine.reset_state(FSM_ID, "OFF")

        assert engine.get_last_transition_time(FSM_ID) == recorded

    async def test_should_use_provided_wall_clock_when_note_transition_called(
        self, engine: FSMEngine
    ) -> None:
        """Время можно задать явно — для восстановления из хранилища."""
        engine.register_definition(make_definition())

        engine.note_transition(FSM_ID, "2026-10-01T14:23:11.482913")

        assert engine.get_last_transition_time(FSM_ID) == "2026-10-01T14:23:11.482913"
