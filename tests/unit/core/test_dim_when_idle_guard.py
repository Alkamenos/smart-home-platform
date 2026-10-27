"""Вечерняя яркость без движения: условие «оставить 3 %» (B104).

Условие включается только у лампы с ``dim_when_idle`` и только вечером:
после полудня и при солнце под горизонтом. Утром темнота — предрассветная,
и свет должен гаснуть, а не оставаться минимальной яркостью.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.guards.lighting import make_dims_when_idle


TZ = ZoneInfo("Asia/Yekaterinburg")
EVENING = datetime(2026, 10, 27, 20, 0, tzinfo=TZ)
MORNING = datetime(2026, 10, 27, 8, 0, tzinfo=TZ)


def _guard(at: datetime) -> Any:
    """Условие с зафиксированным временем дома."""
    return make_dims_when_idle(now=lambda tz: at.astimezone(tz))


def _context(**overrides: Any) -> dict[str, Any]:
    """Контекст лампы с вечерней яркостью."""
    context: dict[str, Any] = {
        "dim_when_idle": True,
        "daylight": False,
        "time_zone": "Asia/Yekaterinburg",
    }
    context.update(overrides)
    return context


class TestDimWhenIdle:
    """Когда отсутствие движения оставляет 3 %, а когда гасит свет."""

    def test_evening_darkness_keeps_dim(self) -> None:
        """Вечером, солнце под горизонтом — остаёмся на 3 %."""
        assert _guard(EVENING)(None, _context()) is True

    def test_morning_darkness_turns_off(self) -> None:
        """Утром до полудня темнота — предрассветная, тусклый свет не нужен."""
        assert _guard(MORNING)(None, _context()) is False

    def test_daylight_turns_off(self) -> None:
        """Днём свет не оставляют тусклым — это не вечер."""
        assert _guard(EVENING)(None, _context(daylight=True)) is False

    def test_disabled_for_other_lamps(self) -> None:
        """Без параметра вечерняя яркость не включается."""
        context = _context(dim_when_idle=False)
        assert _guard(EVENING)(None, context) is False

    def test_deny_reason_is_named(self) -> None:
        """Отказ называет причину, а не молчит."""
        guard = _guard(MORNING)
        reason = guard.deny_reason(None, _context())
        assert reason == "not_evening"
