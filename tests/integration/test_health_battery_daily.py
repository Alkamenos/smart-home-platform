"""Суточная проверка батарейки не дублирует проблему между обходами."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.persistence.health_store import HealthStore
from core.services.health_registry import HealthRegistry
from core.services.house_health import HouseHealthService


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер с одной батарейкой 15 %."""

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние батарейки.

        Returns:
            Список состояний.
        """
        return [
            {
                "entity_id": "sensor.guest_battery",
                "state": "15",
                "last_updated": (NOW - timedelta(hours=1)).isoformat(),
                "attributes": {"device_class": "battery", "friendly_name": "Гостевая"},
            }
        ]


@pytest.mark.asyncio
async def test_two_sweeps_one_problem(tmp_path) -> None:
    """Повторный обход подтверждает проблему, а не создаёт вторую."""
    registry = HealthRegistry(
        HealthStore(tmp_path / "health.json"),
        clock=lambda: NOW,
    )
    service = HouseHealthService(
        adapter=_Adapter(),
        areas={"sensor.guest_battery": ("комната", "Гостевая")},
        clock=lambda: NOW,
        registry=registry,
        battery_silent_hours=48,
    )

    first = await service.sweep()
    second = await service.sweep()

    assert [problem["kind"] for problem in first["problems"]] == ["low_battery"]
    assert registry.snapshot()["count"] == 1
    assert second["problems"][0]["kind"] == "low_battery"
