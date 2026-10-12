"""Включение света задаёт яркость и цвет явно (требование владельца 2026-10-13).

Боевой случай: «свет над столом» вечером работал ночником (красным на 3 %), а
при обычном включении лампа вспоминала последние настройки и снова включалась
красным. Свет надо включать с явными яркостью и цветом, а не «как помнит
прибор» (BACKLOG B48).

Правила совместимости: `brightness_pct` сильнее `brightness`, `color_temp_kelvin`
сильнее `rgb_color`. Пустые значения означают «эту ось не трогать» — так свет,
не умеющий менять цвет, не получит чужих полей.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


def _turn_on(context: dict[str, Any]) -> dict[str, Any]:
    """Собрать данные команды включения света.

    Args:
        context: Контекст перехода.

    Returns:
        Данные команды.
    """
    intent = ACTION_HANDLERS["turn_on_light"](None, context)
    assert intent is not None
    return intent.data


class TestExplicitBrightnessAndColor:
    """Яркость и цвет уходят в команду, если заданы поведением."""

    def test_brightness_pct_and_color_temp_are_sent(self) -> None:
        """Заданы проценты и цветовая температура — оба уходят в команду."""
        data = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "brightness_pct": 100,
                "color_temp_kelvin": 3000,
            }
        )
        assert data == {"brightness_pct": 100, "color_temp_kelvin": 3000}

    def test_brightness_pct_wins_over_brightness(self) -> None:
        """Если заданы обе яркости, уходит процентная — как у ночника."""
        data = _turn_on(
            {"entity_id": "light.svet_nad_stolom", "brightness": 255, "brightness_pct": 60}
        )
        assert data == {"brightness_pct": 60}

    def test_color_temp_wins_over_rgb(self) -> None:
        """Если заданы оба цвета, уходит цветовая температура."""
        data = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "color_temp_kelvin": 3000,
                "rgb_color": [255, 0, 0],
            }
        )
        assert data == {"color_temp_kelvin": 3000}

    def test_rgb_is_sent_when_no_color_temp(self) -> None:
        """Без цветовой температуры уходит rgb, если он задан."""
        data = _turn_on({"entity_id": "light.lampa", "rgb_color": [10, 20, 30]})
        assert data == {"rgb_color": [10, 20, 30]}

    def test_no_params_leaves_light_alone(self) -> None:
        """Ничего не задано — команда без данных (свет не перенастраиваем)."""
        assert _turn_on({"entity_id": "light.lampa"}) == {}
