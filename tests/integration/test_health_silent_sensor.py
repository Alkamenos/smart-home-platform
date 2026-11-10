"""Сквозная проверка «датчик пропал и вернулся» на истории событий."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.persistence.event_store import EventStore, SensorEvent
from core.services.health_expectations import HealthExpectations
from core.services.house_health import HouseHealthService


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер с изменяемым состоянием датчика."""

    def __init__(self) -> None:
        self.hours_ago = 3.0

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние с заданным возрастом.

        Returns:
            Список состояний.
        """
        updated = NOW - timedelta(hours=self.hours_ago)
        return [
            {
                "entity_id": "sensor.spalnia_temperature",
                "state": "21.0",
                "last_updated": updated.isoformat(),
                "attributes": {"device_class": "temperature", "friendly_name": "Спальня"},
            }
        ]


def _fill_history(store: EventStore) -> None:
    for index in range(10):
        store.save_sensor_event(
            SensorEvent(
                entity_id="sensor.spalnia_temperature",
                old_state="20.0",
                new_state="21.0",
                event_type="state_change",
                trace_id="t",
                timestamp=NOW.timestamp() - 600 * index,
            )
        )


@pytest.mark.asyncio
async def test_silent_sensor_problem_appears_and_disappears(tmp_path) -> None:
    """Пропавшее показание даёт «молчит», новое — снимает проблему."""
    store = EventStore(db_path=str(tmp_path / "history.db"))
    _fill_history(store)
    adapter = _Adapter()
    service = HouseHealthService(
        adapter=adapter,
        areas={"sensor.spalnia_temperature": ("комната", "Спальня")},
        clock=lambda: NOW,
        expectations=HealthExpectations(
            event_store=store,
            clock=lambda: NOW.timestamp(),
        ),
        stale_min_hours=2,
    )

    first = await service.sweep()
    assert [problem["kind"] for problem in first["problems"]] == ["stale"]

    adapter.hours_ago = 0.05
    second = await service.sweep()

    assert second["problems"] == []
