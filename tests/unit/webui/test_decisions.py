"""Последнее решение автоматики для интерфейса (спека 017, US3, FR-018).

Проверяется то, ради чего сервис заведён: по устройству видно решение
человеческим языком и с временем, а выбор идёт по самому свежему из ключей
автоматов и сущности устройства.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from webui.services.decisions import decision_view


class _FakeEngine:
    """Движок с заранее заданными решениями по ключам."""

    def __init__(self, decisions: dict[str, Any]) -> None:
        self._decisions = decisions

    def explain(self, entity_id: str) -> Any:
        """Вернуть решение по ключу."""
        return self._decisions.get(entity_id)


def _decision(at: float, reason: str) -> SimpleNamespace:
    """Решение движка с заданным временем и причиной."""
    return SimpleNamespace(
        at=at,
        outcome="on",
        reason_code="action_on",
        reason_text=reason,
        trigger="motion_detected",
    )


def test_decision_view_should_return_none_without_engine() -> None:
    """Без движка решений нет."""
    assert decision_view(None, ["light.x_lighting_10"]) is None


def test_decision_view_should_pick_latest_across_keys() -> None:
    """Из нескольких ключей выбирается самое свежее решение."""
    engine = _FakeEngine(
        {
            "light.x_lighting_10": _decision(1000.0, "старое"),
            "light.x": _decision(2000.0, "свежее"),
        }
    )

    view = decision_view(engine, ["light.x_lighting_10", "light.x"])

    assert view is not None
    assert view["reason_text"] == "свежее"
    assert view["trigger"] == "motion_detected"
    assert view["at"].startswith("1970-01-01T00:33:20")


def test_decision_view_should_return_none_when_no_decisions() -> None:
    """Если решений по ключам нет — ответ пуст, а не выдуман."""
    engine = _FakeEngine({})

    assert decision_view(engine, ["light.x", ""]) is None
