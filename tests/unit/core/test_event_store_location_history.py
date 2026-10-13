"""Выборка журнала по нескольким сущностям — история локации (спека 016, FR-006).

История локации — это общая лента её датчиков из того же журнала событий.
Срок хранения и очистка у журнала уже есть, поэтому отдельное хранилище не
заводится: снимок и журнал не разъедутся.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

from core.persistence.event_store import EventStore, SensorEvent


def _store(tmp_path: Path) -> EventStore:
    """Журнал во временном каталоге.

    Args:
        tmp_path: Временный каталог теста.

    Returns:
        Хранилище журнала.
    """
    return EventStore(str(tmp_path / "history.db"))


def _event(entity_id: str, value: str, at: float) -> SensorEvent:
    """Запись журнала.

    Args:
        entity_id: Сущность.
        value: Новое состояние.
        at: Время (epoch).

    Returns:
        Запись.
    """
    return SensorEvent(
        entity_id=entity_id,
        old_state="",
        new_state=value,
        event_type="state_changed",
        trace_id=None,
        timestamp=at,
    )


class TestLocationHistorySelection:
    """Выборка по сущностям локации."""

    def test_only_requested_entities_are_returned(self, tmp_path: Path) -> None:
        """Чужие сущности в историю локации не попадают."""
        store = _store(tmp_path)
        store.save_sensor_event(_event("sensor.t_spalnia", "22.4", 100.0))
        store.save_sensor_event(_event("sensor.chuzhoi", "99", 100.0))

        events = store.get_events_for_entities(["sensor.t_spalnia"])

        assert [event.entity_id for event in events] == ["sensor.t_spalnia"]

    def test_all_location_sensors_are_collected(self, tmp_path: Path) -> None:
        """История локации собирает ленту всех её датчиков."""
        store = _store(tmp_path)
        store.save_sensor_event(_event("sensor.t_spalnia", "22.4", 100.0))
        store.save_sensor_event(_event("binary_sensor.m_spalnia", "on", 200.0))

        events = store.get_events_for_entities(["sensor.t_spalnia", "binary_sensor.m_spalnia"])

        assert len(events) == 2

    def test_newest_first(self, tmp_path: Path) -> None:
        """Записи идут новыми первыми: свежее важнее."""
        store = _store(tmp_path)
        store.save_sensor_event(_event("sensor.t", "1", 100.0))
        store.save_sensor_event(_event("sensor.t", "2", 200.0))

        events = store.get_events_for_entities(["sensor.t"])

        assert [event.new_state for event in events] == ["2", "1"]

    def test_interval_filters_records(self, tmp_path: Path) -> None:
        """Интервал отсекает то, что вне его."""
        store = _store(tmp_path)
        store.save_sensor_event(_event("sensor.t", "старое", 100.0))
        store.save_sensor_event(_event("sensor.t", "новое", 300.0))

        events = store.get_events_for_entities(["sensor.t"], from_ts=200.0, to_ts=400.0)

        assert [event.new_state for event in events] == ["новое"]

    def test_limit_is_respected(self, tmp_path: Path) -> None:
        """Ограничение числа записей соблюдается."""
        store = _store(tmp_path)
        for index in range(5):
            store.save_sensor_event(_event("sensor.t", str(index), 100.0 + index))

        events = store.get_events_for_entities(["sensor.t"], limit=2)

        assert len(events) == 2

    def test_empty_entity_list_returns_nothing(self, tmp_path: Path) -> None:
        """Локация без датчиков — пустая история, без обращения к базе."""
        assert _store(tmp_path).get_events_for_entities([]) == []


def test_no_events_is_not_an_error(tmp_path: Path) -> None:
    """Пустая история — это пустая история, а не ошибка.

    Returns:
        Ничего.
    """
    store = _store(tmp_path)

    assert store.get_events_for_entities(["sensor.t"]) == []
