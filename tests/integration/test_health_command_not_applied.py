"""Команда принята, но прибор не изменился — проблема в обходе дома."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from core.commands.expectations import CommandExpectationTracker
from core.services.house_health import HouseHealthService


NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер с одним прибором и изменяемым состоянием."""

    def __init__(self, state: str) -> None:
        self.state = state

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние прибора.

        Returns:
            Список состояний.
        """
        return [
            {
                "entity_id": "light.probe",
                "state": self.state,
                "last_updated": (NOW - timedelta(seconds=10)).isoformat(),
                "attributes": {"friendly_name": "Свет", "device_class": None},
            }
        ]


def _tracker() -> CommandExpectationTracker:
    return CommandExpectationTracker(clock=lambda: (NOW - timedelta(minutes=6)).timestamp())


def _service(adapter: _Adapter, tracker: CommandExpectationTracker) -> HouseHealthService:
    return HouseHealthService(
        adapter=adapter,
        areas={"light.probe": ("комната", "Спальня")},
        clock=lambda: NOW,
        command_expectations=tracker,
        command_grace_minutes=5,
    )


@pytest.mark.asyncio
async def test_unapplied_command_becomes_problem() -> None:
    """Через шесть минут команда turn_on, а прибор off — проблема."""
    tracker = _tracker()
    tracker.record("light.probe", "light", "turn_on")
    service = _service(_Adapter("off"), tracker)

    report = await service.sweep()

    kinds = [problem["kind"] for problem in report["problems"]]
    assert kinds == ["command_not_applied"]
    assert "turn_on" in report["problems"][0]["detail"]


@pytest.mark.asyncio
async def test_applied_command_is_not_a_problem() -> None:
    """Прибор включился — проблемы нет, ожидание снято."""
    tracker = _tracker()
    tracker.record("light.probe", "light", "turn_on")
    service = _service(_Adapter("on"), tracker)

    report = await service.sweep()

    assert report["problems"] == []
    assert tracker.pending(NOW.timestamp()) == ()


@pytest.mark.asyncio
async def test_transitional_state_waits() -> None:
    """Штора ещё едет — это не провал команды."""
    tracker = _tracker()
    tracker.record("light.probe", "cover", "open_cover")
    service = _service(_Adapter("opening"), tracker)

    report = await service.sweep()

    assert report["problems"] == []
    assert tracker.pending(NOW.timestamp())


def test_command_problem_reaches_registry_and_snapshot(tmp_path) -> None:
    """Сводка с неприменённой командой попадает в реестр и API."""
    from core.persistence.health_store import HealthStore
    from core.services.health_registry import HealthRegistry
    from core.services.problems import compose_report

    registry = HealthRegistry(HealthStore(tmp_path / "health.json"), clock=lambda: NOW)
    report = compose_report(
        None,
        None,
        registry=registry,
        extra_problems=[
            {
                "kind": "command_not_applied",
                "subject": "light.probe",
                "name": "Свет",
                "area": "Спальня",
                "detail": "команда turn_on не применена",
            }
        ],
    )

    assert report["count"] == 1
    snapshot = registry.snapshot()
    assert snapshot["count"] == 1
    assert snapshot["problems"][0]["reasons"][0]["kind"] == "command_not_applied"
