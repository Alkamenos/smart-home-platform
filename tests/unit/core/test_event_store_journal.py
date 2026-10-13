"""Общая лента журнала: query_journal (спека 017, US4).

Проверяется то, ради чего метод заведён: события датчиков и переходы автоматов
складываются в одну ленту, новые первыми, с фильтрами по сущности и трассировке.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from core.persistence.event_store import EventStore, FsmTransition, SensorEvent


def _store(tmp_path: Path) -> EventStore:
    """Хранилище во временном каталоге.

    Args:
        tmp_path: Временный каталог теста.

    Returns:
        Хранилище журнала.
    """
    return EventStore(str(tmp_path / "history.db"))


def test_journal_should_merge_events_and_transitions(tmp_path: Path) -> None:
    """Лента объединяет события и переходы, новые первыми."""
    store = _store(tmp_path)
    store.save_sensor_event(
        SensorEvent(
            entity_id="sensor.t",
            old_state="21",
            new_state="22",
            event_type="state_change",
            trace_id="t1",
            timestamp=100.0,
        )
    )
    store.save_fsm_transition(
        FsmTransition(
            entity_id="light.x_lighting_10",
            from_state="OFF",
            to_state="ON",
            trigger_name="motion",
            trace_id="t1",
            timestamp=200.0,
        )
    )

    rows = store.query_journal(limit=10)

    assert [row["kind"] for row in rows] == ["transition", "event"]
    assert rows[0]["trigger_name"] == "motion"
    assert rows[1]["new_state"] == "22"


def test_journal_should_expose_rejected_transition(tmp_path: Path) -> None:
    """Отклонённый переход отличим от выполненного."""
    store = _store(tmp_path)
    store.save_fsm_transition(
        FsmTransition(
            entity_id="light.x_lighting_10",
            from_state="OFF",
            to_state="OFF",
            trigger_name="motion",
            trace_id=None,
            timestamp=100.0,
            success=False,
            reason="quiet_hours",
        )
    )

    rows = store.query_journal(limit=10)

    assert rows[0]["success"] == 0
    assert rows[0]["reason"] == "quiet_hours"


def test_journal_should_filter_by_entity_and_trace(tmp_path: Path) -> None:
    """Фильтры по сущности и трассировке работают."""
    store = _store(tmp_path)
    store.save_sensor_event(
        SensorEvent(
            entity_id="sensor.a",
            old_state="0",
            new_state="1",
            event_type="state_change",
            trace_id="t1",
            timestamp=100.0,
        )
    )
    store.save_sensor_event(
        SensorEvent(
            entity_id="sensor.b",
            old_state="0",
            new_state="1",
            event_type="state_change",
            trace_id="t2",
            timestamp=200.0,
        )
    )

    by_entity = store.query_journal(entity_ids=["sensor.a"], limit=10)
    by_trace = store.query_journal(trace_id="t2", limit=10)

    assert [row["entity_id"] for row in by_entity] == ["sensor.a"]
    assert [row["entity_id"] for row in by_trace] == ["sensor.b"]


def test_journal_should_empty_for_empty_entity_filter(tmp_path: Path) -> None:
    """Пустой список сущностей — пустая лента, а не «все записи»."""
    store = _store(tmp_path)
    store.save_sensor_event(
        SensorEvent(
            entity_id="sensor.a",
            old_state="0",
            new_state="1",
            event_type="state_change",
            trace_id=None,
            timestamp=100.0,
        )
    )

    assert store.query_journal(entity_ids=[], limit=10) == []


def test_journal_should_respect_before_cursor(tmp_path: Path) -> None:
    """Курсор `before` отдаёт только записи старше момента."""
    store = _store(tmp_path)
    for timestamp in (100.0, 200.0, 300.0):
        store.save_sensor_event(
            SensorEvent(
                entity_id="sensor.a",
                old_state="0",
                new_state="1",
                event_type="state_change",
                trace_id=None,
                timestamp=timestamp,
            )
        )

    rows = store.query_journal(before_ts=250.0, limit=10)

    assert [row["timestamp"] for row in rows] == [200.0, 100.0]
