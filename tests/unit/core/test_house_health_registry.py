"""Обход дома отдаёт проблемы реестру и не ломает старый снимок."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from core.persistence.health_store import HealthStore
from core.services.health_registry import HealthRegistry
from core.services.house_health import HouseHealthService
from core.services.problems import compose_report, levels_for


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


class _Adapter:
    """Адаптер-двойник: один недоступный датчик."""

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Отдать состояние датчика.

        Returns:
            Список состояний.
        """
        return [
            {
                "entity_id": "sensor.spalnia_temperature",
                "state": "unavailable",
                "last_updated": NOW.isoformat(),
                "attributes": {"device_class": "temperature", "friendly_name": "Спальня"},
            }
        ]


class _EmptyAdapter:
    """Адаптер-двойник: дом не прочитался."""

    async def get_all_states(self) -> list[dict[str, Any]]:
        """Вернуть пустой список.

        Returns:
            Пустой список.
        """
        return []


class _Registry:
    """Реестр-двойник: запоминает вызовы."""

    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, Any]], str, str | None]] = []

    def observe_report(
        self,
        problems: list[dict[str, Any]],
        generated_at: str,
        *,
        source: str | None = None,
        close_missing: bool = True,
    ) -> list[dict[str, Any]]:
        """Запомнить снимок.

        Args:
            problems: Проблемы.
            generated_at: Время.
            source: Источник.
            close_missing: Закрывать ли пропавшие.

        Returns:
            Пустой список (не используется).
        """
        self.calls.append((list(problems), generated_at, source))
        return []


@pytest.mark.asyncio
async def test_sweep_should_pass_problems_to_registry() -> None:
    """Обход отдаёт найденные проблемы реестру с источником health."""
    registry = _Registry()
    service = HouseHealthService(
        adapter=_Adapter(),
        areas={"sensor.spalnia_temperature": ("комната", "Спальня")},
        clock=lambda: NOW,
        registry=registry,
    )

    report = await service.sweep()

    assert registry.calls, "обход не передал проблемы реестру"
    problems, generated_at, source = registry.calls[0]
    assert problems and problems[0]["kind"] == "unavailable"
    assert generated_at == NOW.isoformat()
    assert source == "health"
    # Старый снимок остаётся плоским: его читают дашборд и тесты.
    assert report["problems"][0]["subject"] == "sensor.spalnia_temperature"


def test_compose_report_should_add_levels_and_count() -> None:
    """Сводка получает count и levels, не меняя плоский список."""
    report = compose_report(
        {
            "generated_at": NOW.isoformat(),
            "sensor_count": 1,
            "problems": [{"kind": "stale", "subject": "sensor.x", "detail": "молчит"}],
        },
        None,
    )

    assert report["count"] == 1
    assert report["levels"] == {"info": 0, "warning": 1, "critical": 0}
    assert levels_for(report["problems"]) == report["levels"]


def test_compose_report_should_observe_registry() -> None:
    """Сводка передаёт объединённые проблемы реестру."""
    registry = _Registry()

    compose_report(
        {
            "generated_at": NOW.isoformat(),
            "sensor_count": 1,
            "problems": [{"kind": "stale", "subject": "sensor.x", "detail": "молчит"}],
        },
        None,
        registry=registry,
    )

    assert registry.calls
    assert registry.calls[0][0][0]["kind"] == "stale"


@pytest.mark.asyncio
async def test_unreadable_house_should_not_close_existing_problems(tmp_path) -> None:
    """Пустой ответ дома не объявляет датчики здоровыми."""
    store = HealthStore(tmp_path / "health.json")
    registry = HealthRegistry(store, clock=lambda: NOW)
    registry.observe_report(
        [{"kind": "stale", "subject": "sensor.x", "detail": "молчит"}],
        NOW.isoformat(),
    )
    service = HouseHealthService(
        adapter=_EmptyAdapter(),
        areas={"sensor.x": ("комната", "Спальня")},
        clock=lambda: NOW,
        registry=registry,
    )

    await service.sweep()

    kinds = {problem.kind for problem in registry.active}
    assert "stale" in kinds, "проблема датчика закрыта из-за недоступного дома"
    assert "house_unreadable" in kinds
