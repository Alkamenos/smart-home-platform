"""Порог молчания берётся у конкретного датчика, а не общий."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.models.health import SensorExpectation
from core.services.house_health import HouseHealthService


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер-двойник с одним состоянием."""

    def __init__(self, item: dict[str, Any]) -> None:
        self.item = item

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние.

        Returns:
            Список из одного состояния.
        """
        return [self.item]


class _Expectations:
    """Ожидание-двойник с заданным порогом."""

    def __init__(self, stale_after_sec: float, interval_sec: float = 600) -> None:
        self.stale_after_sec = stale_after_sec
        self.interval_sec = interval_sec

    def expectation(
        self, entity_id: str, device_class: str | None, now_ts: float | None = None
    ) -> SensorExpectation:
        """Вернуть заранее заданное ожидание.

        Args:
            entity_id: Сущность.
            device_class: Класс.
            now_ts: Время.

        Returns:
            Ожидание.
        """
        del device_class, now_ts
        return SensorExpectation(
            entity_id=entity_id,
            expected_interval_sec=self.interval_sec,
            stale_after_sec=self.stale_after_sec,
            source="history",
            samples=5,
        )


def _state(device_class: str, hours_ago: float) -> dict[str, Any]:
    updated = NOW - timedelta(hours=hours_ago)
    return {
        "entity_id": "sensor.probe",
        "state": "21.0",
        "last_updated": updated.isoformat(),
        "attributes": {"device_class": device_class, "friendly_name": "Датчик"},
    }


def _service(expectations: _Expectations, item: dict[str, Any]) -> HouseHealthService:
    return HouseHealthService(
        adapter=_Adapter(item),
        areas={"sensor.probe": ("комната", "Спальня")},
        clock=lambda: NOW,
        expectations=expectations,
        stale_min_hours=2,
    )


@pytest.mark.asyncio
async def test_age_below_own_threshold_is_not_stale() -> None:
    """Три часа при пороге четыре — не проблема."""
    report = await _service(_Expectations(4 * 3600), _state("temperature", 3)).sweep()

    assert report["problems"] == []


@pytest.mark.asyncio
async def test_age_above_own_threshold_is_stale_with_expectation() -> None:
    """Три часа при пороге два — «молчит» с ожиданием в причине."""
    report = await _service(_Expectations(2 * 3600), _state("temperature", 3)).sweep()

    problem = report["problems"][0]
    assert problem["kind"] == "stale"
    assert "при ожидании 10 мин" in problem["detail"]


@pytest.mark.asyncio
async def test_motion_sensor_is_not_called_silent() -> None:
    """Событийный датчик движения не тревожит из-за тишины."""
    report = await _service(_Expectations(2 * 3600), _state("motion", 10)).sweep()

    assert report["problems"] == []


@pytest.mark.asyncio
async def test_fresh_reading_is_not_stale() -> None:
    """Свежее показание не проблема."""
    report = await _service(_Expectations(2 * 3600), _state("temperature", 0.1)).sweep()

    assert report["problems"] == []
