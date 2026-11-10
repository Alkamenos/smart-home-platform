"""История событий отдаёт метки для расчёта интервала датчика."""

from __future__ import annotations

from core.persistence.event_store import EventStore, SensorEvent


def _event(entity_id: str, timestamp: float) -> SensorEvent:
    return SensorEvent(
        entity_id=entity_id,
        old_state="on",
        new_state="off",
        event_type="state_change",
        trace_id="t",
        timestamp=timestamp,
    )


def test_timestamps_are_sorted_and_filtered(tmp_path) -> None:
    """Метки после порога отдаются по возрастанию, чужие — нет."""
    store = EventStore(db_path=str(tmp_path / "history.db"))
    for moment in (300.0, 100.0, 200.0):
        store.save_sensor_event(_event("sensor.a", moment))
    store.save_sensor_event(_event("sensor.b", 250.0))

    values = store.event_timestamps_since("sensor.a", 150.0)

    assert values == [200.0, 300.0]


def test_missing_entity_returns_empty(tmp_path) -> None:
    """Нет событий — пустой список, без ошибки."""
    store = EventStore(db_path=str(tmp_path / "history.db"))

    assert store.event_timestamps_since("sensor.none", 0.0) == []
