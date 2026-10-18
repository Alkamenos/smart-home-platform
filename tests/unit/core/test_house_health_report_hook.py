"""Снимок обхода дома отдаётся наружу — зеркалу проблем (B79).

Карточка тревог на дашборде Home Assistant живёт не сама по себе: обход дома
каждый раз считает проблемы, и этот снимок должен уходить в дом. Здесь
проверяется стык: обход **отдаёт** снимок подписчику, отказ подписчика не ломает
обход, а без подписчика обход работает как раньше.

Проверять стык отдельно стоит потому, что отказ публикации в MQTT — обычное
дело (брокер перезапускается), и он не должен превращаться в «обход дома
сломался».
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from core.services.house_health import HouseHealthService


NOW = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)


class FakeAdapter:
    """Адаптер-двойник: отдаёт заданные состояния."""

    def __init__(self, states: list[dict[str, Any]]) -> None:
        self.states = states

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояния.

        Returns:
            Список состояний.
        """
        return self.states


def _state() -> dict[str, Any]:
    """Одно живое показание температуры.

    Returns:
        Словарь состояния.
    """
    return {
        "entity_id": "sensor.a_temperature",
        "state": "21.0",
        "attributes": {"device_class": "temperature", "unit_of_measurement": "°C"},
        "last_updated": NOW.isoformat(),
        "last_changed": NOW.isoformat(),
    }


def _service(on_report: Any | None = None) -> HouseHealthService:
    """Служба обхода с одним датчиком.

    Args:
        on_report: Подписчик на снимок либо None.

    Returns:
        Служба обхода.
    """
    return HouseHealthService(
        adapter=FakeAdapter([_state()]),
        areas={"sensor.a_temperature": ("комната", "Гостиная")},
        clock=lambda: NOW,
        on_report=on_report,
    )


class TestReportHook:
    """Снимок обхода уходит подписчику."""

    @pytest.mark.asyncio
    async def test_report_is_handed_to_the_mirror(self) -> None:
        """Подписчик получает ровно тот снимок, который вернул обход."""
        seen: list[dict[str, Any]] = []

        async def on_report(report: dict[str, Any]) -> None:
            seen.append(report)

        report = await _service(on_report).sweep()

        assert seen == [report], "снимок обхода не дошёл до зеркала"

    @pytest.mark.asyncio
    async def test_mirror_failure_does_not_break_the_sweep(self) -> None:
        """Отказ публикации в MQTT не отменяет обход дома."""

        async def on_report(report: dict[str, Any]) -> None:
            raise RuntimeError("брокер недоступен")

        report = await _service(on_report).sweep()

        assert report["generated_at"] == NOW.isoformat()
        assert "problems" in report

    @pytest.mark.asyncio
    async def test_no_hook_means_no_work(self) -> None:
        """Без подписчика обход работает как прежде."""
        report = await _service().sweep()

        assert report["sensor_count"] == 1
