"""Суточный цикл контейнера берёт часы из расписания дома (B76, A3).

Раньше ``night_off_at`` и ``morning_at`` лежали в правилах освещения, хотя эти
события получают все автоматы. Проверка держит новый адрес полей: если
контейнер снова начнёт читать ``automation_rules.lighting``, тест покраснеет.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from core.container import Container
from core.models.manifest import AutomationRules, HouseSchedule, InstanceConfig, Manifest


def _manifest() -> Manifest:
    """Манифест с расписанием дома и без комнат.

    Returns:
        Минимальный манифест для проверки часов.
    """
    return Manifest(
        version=1,
        instance=InstanceConfig(
            id="probe", name="Probe", owner="probe", created_at="2026-01-01T00:00:00Z"
        ),
        rooms=[],
        automation_rules=AutomationRules(
            time_zone="Asia/Yekaterinburg",
            schedule=HouseSchedule(night_off_at="22:15", morning_at="06:45"),
        ),
    )


@pytest.mark.asyncio
async def test_day_cycle_uses_house_schedule(monkeypatch: Any) -> None:
    """Контейнер передаёт в часы события из ``automation_rules.schedule``.

    Args:
        monkeypatch: Подмена часов и сервиса цикла.

    Returns:
        Ничего.
    """
    captured: dict[str, Any] = {}

    class FakeClock:
        """Часы, запоминающие расписание."""

        def __init__(self, events: dict[dt.time, str], timezone: Any) -> None:
            captured["events"] = events
            captured["timezone"] = timezone

    class FakeService:
        """Сервис цикла, который не запускает фоновую задачу."""

        def __init__(self, clock: Any, engine: Any) -> None:
            captured["clock"] = clock
            captured["engine"] = engine

        def start(self) -> None:
            captured["started"] = True

        def describe(self) -> str:
            return "fake day cycle"

    monkeypatch.setattr("core.scheduling.daily.DailyClock", FakeClock)
    monkeypatch.setattr("core.services.day_cycle.DayCycleService", FakeService)

    container = Container(manifest=_manifest())
    container._fsm = object()  # type: ignore[assignment]  # noqa: SLF001
    container._start_day_cycle()  # noqa: SLF001

    assert captured["events"] == {
        dt.time(22, 15): "quiet_hours_started",
        dt.time(6, 45): "day_started",
    }
    assert str(captured["timezone"]) == "Asia/Yekaterinburg"
    assert captured["started"] is True
