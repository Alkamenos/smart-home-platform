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

    def test_global_color_temp_is_used_when_enabled(self) -> None:
        """Свет с флагом глобальной температуры берёт текущее значение дома."""
        data = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "brightness_pct": 100,
                "use_global_color_temp": True,
                "color_temp_current": 4200.0,
            }
        )
        assert data == {"brightness_pct": 100, "color_temp_kelvin": 4200}

    def test_global_color_temp_falls_back_to_day_or_night(self) -> None:
        """Нет текущего значения — берётся дневная или ночная граница."""
        day = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "use_global_color_temp": True,
                "daylight": True,
                "color_temp_day": 6000,
                "color_temp_night": 2000,
            }
        )
        assert day["color_temp_kelvin"] == 6000

        night = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "use_global_color_temp": True,
                "daylight": False,
                "color_temp_day": 6000,
                "color_temp_night": 2000,
            }
        )
        assert night["color_temp_kelvin"] == 2000

    def test_explicit_color_temp_wins_over_global(self) -> None:
        """Явная температура устройства сильнее общей — особую лампу не ломаем."""
        data = _turn_on(
            {
                "entity_id": "light.svet_nad_stolom",
                "use_global_color_temp": True,
                "color_temp_current": 4200,
                "color_temp_kelvin": 3000,
            }
        )
        assert data["color_temp_kelvin"] == 3000


class TestNightPreparationOnTurnOff:
    """Перед выключением лампа с ночником получает ночной режим."""

    def test_turn_off_prepares_night_state_first(self) -> None:
        """Сначала 3 % красного, затем выключение — иначе ночник вспыхнет ярким."""
        result = ACTION_HANDLERS["turn_off_light"](
            None,
            {"entity_id": "light.svet_nad_stolom", "prepare_for_night": True},
        )
        assert isinstance(result, list), "нет подготовки ночного состояния"
        assert [intent.service for intent in result] == ["turn_on", "turn_off"]
        night = result[0]
        assert night.data["brightness_pct"] == 3
        assert night.data["rgb_color"] == [255, 0, 0]
        assert night.data["transition"] == 0

    def test_turn_off_without_night_keeps_single_command(self) -> None:
        """Обычная лампа гасится одной командой, без красной вспышки."""
        result = ACTION_HANDLERS["turn_off_light"](None, {"entity_id": "light.lampa"})
        assert not isinstance(result, list)
        assert result is not None and result.service == "turn_off"  # type: ignore[union-attr]
