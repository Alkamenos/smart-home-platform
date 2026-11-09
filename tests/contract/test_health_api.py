"""Контракт API здоровья: единый список и совместимый /health."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from webui.routes.health import health, problems


class _Service:
    """Служба обхода-двойник: отдаёт готовый снимок."""

    last_report = {
        "generated_at": "2026-11-09T12:00:00+05:00",
        "sensor_count": 1,
        "problems": [
            {
                "kind": "stale",
                "subject": "sensor.spalnia_temperature",
                "name": "Спальня",
                "area": "Спальня",
                "detail": "молчит 2 ч",
            }
        ],
    }


class _Container:
    """Контейнер-двойник."""

    house_health = _Service()

    def problems_snapshot(self) -> dict[str, Any]:
        """Единый снимок.

        Returns:
            Снимок с группой проблем.
        """
        return {
            "generated_at": "2026-11-09T12:00:00+05:00",
            "count": 1,
            "levels": {"info": 0, "warning": 1, "critical": 0},
            "problems": [
                {
                    "id": "abc",
                    "subject": "sensor.spalnia_temperature",
                    "name": "Спальня",
                    "area": "Спальня",
                    "level": "warning",
                    "first_seen": "2026-11-09T10:00:00+05:00",
                    "last_seen": "2026-11-09T12:00:00+05:00",
                    "reasons": [{"kind": "stale", "detail": "молчит 2 ч"}],
                }
            ],
        }


def _request() -> Any:
    """Запрос с фальшивым приложением и контейнером."""
    app = SimpleNamespace(state=SimpleNamespace(container=_Container()))
    return SimpleNamespace(app=app)


@pytest.mark.asyncio
async def test_health_should_return_count_and_levels() -> None:
    """Старый /health получает count и levels, не теряя problems."""
    response = await health(_request())

    payload = json.loads(response.body)
    assert payload["count"] == 1
    assert payload["levels"]["warning"] == 1
    assert payload["problems"][0]["kind"] == "stale"


@pytest.mark.asyncio
async def test_problems_should_return_grouped_snapshot() -> None:
    """Новый /api/v1/problems отдаёт группы с first_seen и reasons."""
    response = await problems(_request())

    payload = json.loads(response.body)
    assert payload["count"] == 1
    assert payload["problems"][0]["first_seen"]
    assert payload["problems"][0]["reasons"][0]["kind"] == "stale"
