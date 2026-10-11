"""Условия и действия вентиляции: рекуператор и вытяжка.

Спека 014, US3, FR-019…FR-030. Дом описан в `research.md` D7 и D13:

- у рекуператора ``preset_mode`` (Приток, Приток MAX, Рекуперация (зима),
  Рекуперация (лето), Вытяжка, Вытяжка MAX, Ночной) и ``percentage`` — **две
  независимые оси**. Физику теплообмена платформа не считает: режим выбирается
  из списка устройства, скорость задаётся отдельной командой;
- скорость = ``speed_normal + |улица − комната| × speed_delta_gain``, с нулём
  в мёртвой зоне ``delta_deadband``, ограничением 0–100 и ночным потолком,
  который **только понижает**;
- выключалка владельца сильнее любого правила: ``ventilation_on = off`` даёт
  скорость 0, и ни одно условие её не поднимает (FR-027);
- проветривание включается человеком и само отключается по таймеру (FR-024).

Три урока из боя 2026-10-11 зашиты в проверки: ключ должен **доезжать** до
действия (а не только читаться), в данных команды лежит **ровно то, что
принимает Home Assistant**, и порядок шагов **осмыслен**.

Покрытие новых действий — 100 % (конституция II).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


#: Параметры по умолчанию из `data-model.md` §5 — как их видит действие.
DEFAULTS = {
    "mode_supply": "Приток",
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_night": "Ночной",
    "mode_airing": "Приток MAX",
    "mode_exhaust": "Вытяжка",
    "speed_normal": 30,
    "speed_delta_gain": 5.0,
    "speed_night_max": 20,
    "delta_deadband": 0.3,
}


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция (state, context) -> CommandIntent либо список шагов.

    Raises:
        AssertionError: действия нет в реестре — шаблон его не найдёт.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: в реестре {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


def _steps(result: Any) -> list[Any]:
    """Шаги команды: одно намерение — список из одного.

    Args:
        result: То, что вернуло действие.

    Returns:
        Список шагов.
    """
    if result is None:
        return []
    return list(result) if isinstance(result, list) else [result]


class TestModeForWeather:
    """Режим выбирается по погоде, а не вычисляется физикой."""

    def test_cold_outside_picks_winter_mode(self) -> None:
        """На улице холоднее порога — режим зимы.

        Returns:
            Ничего.
        """
        guard = _action("mode_for_weather")
        context = {**DEFAULTS, "outside_temperature": -5.0, "winter_mode_threshold": 5.0}

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_winter"], (
            "на морозе выбран не режим зимы: холодный приток через рекуперацию "
            "и есть обогрев дома без кондиционера"
        )

    def test_warm_outside_picks_summer_mode(self) -> None:
        """На улице теплее порога — режим лета.

        Returns:
            Ничего.
        """
        guard = _action("mode_for_weather")
        context = {**DEFAULTS, "outside_temperature": 18.0, "winter_mode_threshold": 5.0}

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_summer"]

    def test_unreadable_outside_temperature_refuses_with_reason(self) -> None:
        """Нет показания улицы — отказ с названной причиной, а не угадывание.

        Returns:
            Ничего.
        """
        guard = _action("mode_for_weather")
        context = {**DEFAULTS, "outside_temperature": None, "winter_mode_threshold": 5.0}

        assert guard(None, context) is False, (
            "без температуры улицы режим выбран наугад: при морозе это лишний "
            "приток свежего воздуха, летом — душный"
        )
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "outside_temp_missing"
        )


class TestSpeedWithinLimits:
    """Скорость считается по разнице температур и ограничивается."""

    def test_speed_grows_with_difference(self) -> None:
        """Чем больше разница, тем выше скорость.

        Returns:
            Ничего.
        """
        guard = _action("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": 0.0,
            "source_room_temperature": 20.0,
            "is_night": False,
        }

        assert guard(None, context) is True
        # 30 + |0 − 20| × 5 = 130 → ограничено 100
        assert context["percentage"] == 100, (
            f"скорость {context.get('percentage')!r} при разнице 20 °C: "
            "должна упираться в 100, а не уходить за пределы устройства"
        )

    def test_small_difference_falls_in_deadband(self) -> None:
        """В мёртвой зоне скорость обычная, а не скачет от копеек разницы.

        Returns:
            Ничего.
        """
        guard = _action("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": 19.9,
            "source_room_temperature": 20.0,
            "is_night": False,
        }

        assert guard(None, context) is True
        assert context["percentage"] == DEFAULTS["speed_normal"], (
            f"разница 0.1 °C дала скорость {context.get('percentage')!r} вместо "
            f"{DEFAULTS['speed_normal']}: рекуператор не должен дёргаться из-за "
            "колебаний показания на tenth доли градуса"
        )

    def test_night_cap_only_lowers(self) -> None:
        """Ночной потолок только понижает: тихую скорость он не поднимает.

        Returns:
            Ничего.
        """
        guard = _action("speed_within_limits")

        # Мёртвая зона, обычная скорость 30 > ночного потолка 20 → 20
        night = {
            **DEFAULTS,
            "outside_temperature": 20.0,
            "source_room_temperature": 20.0,
            "is_night": True,
        }
        assert guard(None, night) is True
        assert night["percentage"] == DEFAULTS["speed_night_max"]

        # Ночь, но скорость и так ниже потолка (узкий параметр) — не поднимаем
        quiet = {
            **DEFAULTS,
            "speed_normal": 10,
            "speed_night_max": 20,
            "outside_temperature": 20.0,
            "source_room_temperature": 20.0,
            "is_night": True,
        }
        assert guard(None, quiet) is True
        assert quiet["percentage"] == 10, (
            f"ночной потолок поднял скорость до {quiet.get('percentage')!r}: "
            "он ограничивает, а не прибавляет"
        )


class TestOwnerSwitchIsStrongerThanAnyRule:
    """Выключалка владельца сильнее любого правила (FR-027)."""

    def test_switch_off_gives_zero_speed(self) -> None:
        """``ventilation_on = off`` — скорость ноль.

        Returns:
            Ничь.
        """
        guard = _action("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": -20.0,
            "source_room_temperature": 24.0,
            "is_night": False,
            "ventilation_on": False,
        }

        assert guard(None, context) is True
        assert context["percentage"] == 0, (
            f"при ventilation_on = off скорость {context.get('percentage')!r}: "
            "выключалка владельца сильнее любого правила, иначе её нельзя "
            "было бы выключить раз и навсегда"
        )


class TestVentilationActions:
    """Действия рекуператора и вытяжки."""

    def test_fan_set_percentage_sends_only_percentage(self) -> None:
        """Команда скорости: только ``percentage`` — и только домен ``fan``.

        Returns:
            Ничего.
        """
        intent = _action("fan_set_percentage")(
            None,
            {"entity_id": "fan.base_smart", "percentage": 45},
        )
        assert intent is not None

        assert intent.domain == "fan"
        assert intent.service == "set_percentage"
        assert intent.data["percentage"] == 45, (
            f"в команду ушло {intent.data!r}: у сервиса `fan.set_percentage` "
            "нет параметра `value` — Home Assistant отвергнет команду"
        )
        assert set(intent.data) == {"percentage"}, (
            f"в данных команды {sorted(intent.data)}: лишний ключ означает "
            "400 Bad Request и потерю всей команды (боевой дефект 2026-10-11)"
        )

    def test_fan_set_preset_sends_only_preset_mode(self) -> None:
        """Команда режима: только ``preset_mode``.

        Returns:
            Ничего.
        """
        intent = _action("fan_set_preset")(
            None,
            {"entity_id": "fan.base_smart", "preset_mode": "Приток MAX"},
        )
        assert intent is not None

        assert (intent.domain, intent.service) == ("fan", "set_preset_mode")
        assert intent.data["preset_mode"] == "Приток MAX"
        assert set(intent.data) == {"preset_mode"}

    def test_mode_and_speed_are_two_independent_steps(self) -> None:
        """Режим и скорость — две команды: смена скорости не сбрасывает режим.

        Returns:
            Ничего.
        """
        steps = _steps(
            _action("fan_apply_mode_and_speed")(
                None,
                {
                    "entity_id": "fan.base_smart",
                    "preset_mode": "Рекуперация (зима)",
                    "percentage": 60,
                },
            )
        )

        assert len(steps) == 2, (
            f"режим и скорость описаны {len(steps)} шагами вместо двух: у "
            "рекуператора это независимые оси, и одна команда не может задать "
            "обе (FR-021)"
        )
        services = {(step.domain, step.service) for step in steps}
        assert services == {("fan", "set_preset_mode"), ("fan", "set_percentage")}

    def test_exhaust_has_no_speed(self) -> None:
        """Вытяжка без скорости: только вкл/выкл.

        Returns:
            Ничего.
        """
        steps = _steps(
            _action("exhaust_on")(None, {"entity_id": "fan.vykliuchatel_sanuzel_switch2"})
        )

        assert len(steps) == 1
        assert (steps[0].domain, steps[0].service) == ("fan", "turn_on")
        assert not steps[0].data, (
            f"вытяжка получила данные {steps[0].data!r}: у этого прибора нет "
            "скорости, Home Assistant такую команду отвергнет"
        )
