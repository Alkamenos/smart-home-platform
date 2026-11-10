"""Батарейки: низкий заряд и молчание отчёта о заряде."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.persistence.health_store import HealthStore
from core.services.health_registry import HealthRegistry
from core.services.house_health import HouseHealthService


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер-двойник с одной батарейкой."""

    def __init__(self, value: str, hours_ago: float) -> None:
        self.value = value
        self.hours_ago = hours_ago

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние батарейки.

        Returns:
            Список состояний.
        """
        updated = NOW - timedelta(hours=self.hours_ago)
        return [
            {
                "entity_id": "sensor.probe_battery",
                "state": self.value,
                "last_updated": updated.isoformat(),
                "attributes": {"device_class": "battery", "friendly_name": "Батарейка"},
            }
        ]


def _service(value: str, hours_ago: float, **kwargs: Any) -> HouseHealthService:
    return HouseHealthService(
        adapter=_Adapter(value, hours_ago),
        areas={"sensor.probe_battery": ("комната", "Спальня")},
        clock=lambda: NOW,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_low_battery_is_reported() -> None:
    """15 % — «батарейка на исходе»."""
    report = await _service("15", 1).sweep()

    assert [problem["kind"] for problem in report["problems"]] == ["low_battery"]


@pytest.mark.asyncio
async def test_exactly_twenty_percent_is_not_low() -> None:
    """Порог строгий: ровно 20 % ещё не тревога."""
    report = await _service("20", 1).sweep()

    assert report["problems"] == []


@pytest.mark.asyncio
async def test_silent_battery_after_two_days() -> None:
    """49 часов без отчёта — «батарейка молчит», а не общий stale."""
    report = await _service("80", 49).sweep()

    problem = report["problems"][0]
    assert problem["kind"] == "battery_silent"
    assert "не отчитывалась" in problem["detail"]


@pytest.mark.asyncio
async def test_battery_under_two_days_is_not_silent() -> None:
    """47 часов — ещё норма для суточного отчёта."""
    report = await _service("80", 47).sweep()

    assert report["problems"] == []


@pytest.mark.asyncio
async def test_battery_is_not_reported_as_general_stale() -> None:
    """Старое показание батарейки не превращается в stale."""
    report = await _service("80", 49).sweep()

    kinds = [problem["kind"] for problem in report["problems"]]
    assert "stale" not in kinds


@pytest.mark.asyncio
async def test_repeated_sweep_does_not_duplicate_battery_problem(tmp_path) -> None:
    """Второй обход в те же сутки не создаёт вторую запись."""
    registry = HealthRegistry(
        HealthStore(tmp_path / "health.json"),
        clock=lambda: NOW,
    )
    service = _service("15", 1, registry=registry)

    await service.sweep()
    await service.sweep()

    assert registry.snapshot()["count"] == 1
    assert registry.snapshot()["problems"][0]["reasons"][0]["kind"] == "low_battery"
