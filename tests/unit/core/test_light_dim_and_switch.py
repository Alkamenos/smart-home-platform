"""Вечерняя яркость и светильники-выключатели (B104)."""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from core.action_handlers import turn_off_light, turn_on_dim_light, turn_on_light
from core.commands.dispatcher import CommandIntent


class TestDimLight:
    """Вечерний свет: 3 % и общая температура дома, без красного."""

    def test_uses_dim_brightness_and_global_temperature(self) -> None:
        intent = turn_on_dim_light(
            None,
            {
                "entity_id": "light.svet_nad_stolom",
                "dim_brightness_pct": 3,
                "use_global_color_temp": True,
                "color_temp_current": 3000,
            },
        )

        assert intent is not None
        assert intent.data["brightness_pct"] == 3
        assert intent.data["color_temp_kelvin"] == 3000
        assert intent.data["transition"] == 2, "вечернее затухание должно быть плавным"
        assert "rgb_color" not in intent.data, "вечерняя яркость — не красный ночник"

    def test_defaults_to_three_percent(self) -> None:
        intent = turn_on_dim_light(None, {"entity_id": "light.svet_nad_stolom"})

        assert intent is not None
        assert intent.data["brightness_pct"] == 3


class TestSwitchAsLight:
    """Светильник, который Home Assistant отдаёт как switch.*."""

    def test_turn_on_uses_switch_domain_without_light_data(self) -> None:
        intent = turn_on_light(
            None,
            {
                "entity_id": "switch.podsvetka_zerkala",
                "brightness_pct": 100,
                "color_temp_kelvin": 2700,
            },
        )

        assert intent is not None
        assert intent.domain == "switch"
        assert intent.data == {}, "выключателю нельзя передавать яркость и цвет"

    def test_turn_off_does_not_prepare_switch_for_night(self) -> None:
        intent = turn_off_light(
            None,
            {
                "entity_id": "switch.podsvetka_zerkala",
                "prepare_for_night": True,
            },
        )

        assert isinstance(intent, CommandIntent)
        assert intent.domain == "switch"
        assert intent.data == {}
