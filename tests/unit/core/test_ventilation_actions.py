"""Условия и действия вентиляции: рекуператор и вытяжка.

Спека 014, US3, FR-019…FR-056. Дом описан в `research.md` D7, D13 и D22:

- у рекуператора ``preset_mode`` (Приток, Приток MAX, Рекуперация (зима),
  Рекуперация (лето), Вытяжка, Вытяжка MAX, Ночной) и ``percentage`` — **две
  независимые оси**. Физику теплообмена платформа не считает: режим выбирается
  из списка устройства, скорость задаётся отдельной командой;
- обычный режим — по модификатору «зима»: «Рекуперация (зима)» / «Рекуперация
  (лето)». Приток по дельте «комната − улица» отменён (приток остужал дом,
  боевой разбор 2026-10-12);
- жарко выше потолка комфорта — отдельное условие ``should_run_max_supply``
  ведёт автомат в ``AIRING`` («Приток MAX») на таймер, затем возврат;
- скорость = ``speed_normal``, пока улица не холоднее ``speed_cold_reference``;
  холоднее — падает на ``speed_cold_gain`` за градус, не ниже ``speed_min``;
  ночью при нормальной температуре — ``speed_min``;
- выключалка владельца сильнее любого правила: ``ventilation_on = off``
  отказывает с причиной ``turned_off_by_owner``, а переход ``SUPPLY → IDLE``
  гасит прибор (FR-027, T090), а не «крутит на нуле»;
- комнате холоднее уставки вентиляция тоже не нужна: отказ с причиной
  ``room_below_setpoint`` (FR-049) — это правило заменило прежнее «выключать
  при работающем обогреве» (FR-055);
- проветривание и вытяжка — модификаторы с автосбросом в ``false`` по таймеру
  60 минут (T085); вытяжка включается по температуре/влажности санузла (T086).

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
from core.guards.builtin import build_guards


#: Параметры по умолчанию из `data-model.md` §5 — как их видит действие.
DEFAULTS = {
    "mode_summer": "Рекуперация (лето)",
    "mode_winter": "Рекуперация (зима)",
    "mode_airing": "Приток MAX",
    "speed_normal": 43,
    "speed_min": 14,
    "speed_cold_reference": 5.0,
    "speed_cold_gain": 2.0,
}


def _guard(name: str) -> Any:
    """Взять условие по имени из реестра условий.

    Args:
        name: Имя условия.

    Returns:
        Функция (state, context) -> bool с ``deny_reason``.

    Raises:
        AssertionError: условия нет в реестре — шаблон его перехода не найдёт.
    """
    guards = build_guards(control_tracker=None)
    assert name in guards, f"условие `{name}` не зарегистрировано: в реестре {sorted(guards)}"
    return guards[name]


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
        guard = _guard("mode_for_weather")
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
        guard = _guard("mode_for_weather")
        context = {**DEFAULTS, "outside_temperature": 18.0, "winter_mode_threshold": 5.0}

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_summer"]

    def test_unreadable_outside_temperature_refuses_with_reason(self) -> None:
        """Нет показания улицы — отказ с названной причиной, а не угадывание.

        Returns:
            Ничего.
        """
        guard = _guard("mode_for_weather")
        context = {**DEFAULTS, "outside_temperature": None, "winter_mode_threshold": 5.0}

        assert guard(None, context) is False, (
            "без температуры улицы режим выбран наугад: при морозе это лишний "
            "приток свежего воздуха, летом — душный"
        )
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "outside_temp_missing"
        )

    def test_winter_keeps_recuperation_despite_delta(self) -> None:
        """Зимой большая дельта «комната − улица» не включает сырой приток (T094).

        Returns:
            Ничего.
        """
        guard = _guard("mode_for_weather")
        context = {
            **DEFAULTS,
            "outside_temperature": 0.0,
            "is_winter": True,
            "source_room_temperature": 22.0,
            "comfort_max": 25.0,
        }

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_winter"], (
            "зимой при комнате ниже потолка комфорта выбран приток: сырой уличный "
            "воздух охлаждает дом, хотя рекуперация вернула бы тепло "
            "(боевой разбор 2026-10-12)"
        )

    def test_winter_hot_room_still_keeps_recuperation(self) -> None:
        """Жара в комнате — забота `should_run_max_supply`, а не выбора режима.

        `mode_for_weather` отвечает только за обычный режим: зимой им всегда
        остаётся рекуперация. Максимальный приток при жаре — отдельное условие и
        отдельное состояние `AIRING` (FR-050, FR-051).

        Returns:
            Ничего.
        """
        guard = _guard("mode_for_weather")
        context = {
            **DEFAULTS,
            "outside_temperature": 0.0,
            "is_winter": True,
            "temperature": 27.0,
            "comfort_max": 25.0,
        }

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_winter"]

    def test_winter_without_comfort_ceiling_keeps_recuperation(self) -> None:
        """Нет потолка комфорта — приток не выбирается: «жарко» неизвестно.

        Returns:
            Ничего.
        """
        guard = _guard("mode_for_weather")
        context = {
            **DEFAULTS,
            "outside_temperature": 0.0,
            "is_winter": True,
            "source_room_temperature": 30.0,
        }

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_winter"], (
            "без потолка комфорта выбран приток наугад: зимой это лишний сырой "
            "воздух, а «жарко» платформа знать не может"
        )

    def test_summer_keeps_summer_mode_regardless_of_room(self) -> None:
        """Летом обычный режим — «Рекуперация (лето)», какова бы ни была комната.

        Приток по дельте «комната − улица» отменён (research.md D22): охлаждает
        только «Приток MAX» при жаре выше потолка комфорта.

        Returns:
            Ничего.
        """
        guard = _guard("mode_for_weather")
        context = {
            **DEFAULTS,
            "outside_temperature": 24.0,
            "is_winter": False,
            "temperature": 29.0,
        }

        assert guard(None, context) is True
        assert context["chosen_mode"] == DEFAULTS["mode_summer"]


class TestShouldRunMaxSupply:
    """Жарко выше потолка комфорта — максимальный приток с таймером (FR-051)."""

    def test_hot_room_wants_max_supply(self) -> None:
        """Комната строго выше потолка — условие выполняется.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_max_supply")
        context = {**DEFAULTS, "temperature": 26.0, "comfort_max": 25.0}
        assert guard(None, context) is True

    def test_at_comfort_ceiling_is_not_hot(self) -> None:
        """Ровно на потолке — ещё не жарко: приток не включается.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_max_supply")
        context = {**DEFAULTS, "temperature": 25.0, "comfort_max": 25.0}
        assert guard(None, context) is False

    def test_without_comfort_ceiling_refuses(self) -> None:
        """Потолка комфорта нет — «жарко» неизвестно, приток не включаем.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_max_supply")
        context = {**DEFAULTS, "temperature": 30.0}
        assert guard(None, context) is False
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "guard_data_missing"
        )

    def test_owner_switch_off_denies_with_reason(self) -> None:
        """Вентиляция выключена владельцем — причина названа.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_max_supply")
        context = {
            **DEFAULTS,
            "temperature": 30.0,
            "comfort_max": 25.0,
            "ventilation_on": False,
        }
        assert guard(None, context) is False
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "turned_off_by_owner"
        )

    def test_exhaust_role_never_wants_max_supply(self) -> None:
        """Вытяжка санузла притоком не управляет.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_max_supply")
        context = {
            **DEFAULTS,
            "ventilation_role": "exhaust",
            "temperature": 30.0,
            "comfort_max": 25.0,
        }
        assert guard(None, context) is False


class TestSpeedWithinLimits:
    """Скорость зависит от температуры улицы и времени суток (FR-052, FR-053)."""

    def test_warm_outside_keeps_normal_speed(self) -> None:
        """Улица не холоднее опорной — скорость обычная.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": 10.0,
            "temperature": 22.0,
            "is_night": False,
        }

        assert guard(None, context) is True
        assert context["percentage"] == DEFAULTS["speed_normal"]

    def test_colder_outside_lowers_speed(self) -> None:
        """Холоднее опорной — скорость ниже на заданный шаг за градус.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": 0.0,
            "temperature": 22.0,
            "is_night": False,
        }

        assert guard(None, context) is True
        # 43 − (5 − 0) × 2 = 33
        assert context["percentage"] == 33, (
            f"скорость {context.get('percentage')!r} при улице 0 °C: холоднее — "
            "значит тише, чтобы не гнать мороз в дом"
        )

    def test_cold_outside_does_not_go_below_minimum(self) -> None:
        """Мороз не уводит скорость ниже минимума.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": -30.0,
            "temperature": 22.0,
            "is_night": False,
        }

        assert guard(None, context) is True
        assert context["percentage"] == DEFAULTS["speed_min"]

    def test_night_sets_minimum_speed(self) -> None:
        """Ночью при нормальной температуре — минимум, даже если улица тёплая.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": 20.0,
            "temperature": 22.0,
            "is_night": True,
        }

        assert guard(None, context) is True
        assert context["percentage"] == DEFAULTS["speed_min"], (
            f"ночью скорость {context.get('percentage')!r}: тишина важнее "
            "воздухообмена, и минимум не должен подниматься"
        )


class TestOwnerSwitchIsStrongerThanAnyRule:
    """Выключалка владельца сильнее любого правила (FR-027, T090)."""

    def test_switch_off_denies_with_reason(self) -> None:
        """``ventilation_on = off`` — условие отказывает с причиной.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": -20.0,
            "source_room_temperature": 24.0,
            "is_night": False,
            "ventilation_on": False,
        }

        assert guard(None, context) is False, (
            "при ventilation_on = off скорость посчитана: выключалка владельца "
            "сильнее любого правила, и прибор должен быть погашен, а не крутиться"
        )
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "turned_off_by_owner"
        )

    def test_switch_off_stops_recuperator(self) -> None:
        """Переход остановки гасит рекуператор полностью (T090).

        Returns:
            Ничего.
        """
        stop = _guard("ventilation_should_stop")
        context = {**DEFAULTS, "ventilation_on": False}
        assert stop(None, context) is True, (
            "при выключенной вентиляции перехода в IDLE нет: прибор останется "
            "крутиться, хотя владелец выключил вентиляцию"
        )

        intent = _action("fan_turn_off")(None, {"entity_id": "fan.base_smart"})
        assert intent is not None
        assert (intent.domain, intent.service) == ("fan", "turn_off")

    def test_feature_off_also_stops(self) -> None:
        """Фиче-флаг дома выключает вентиляцию целиком (FR-031, T090).

        Returns:
            Ничего.
        """
        stop = _guard("ventilation_should_stop")
        assert stop(None, {**DEFAULTS, "ventilation_enabled": False}) is True

    def test_cold_room_stops_ventilation(self) -> None:
        """Комната холоднее уставки — рекуператор стоит (FR-049).

        Правило по уставке заменило прежнее «выключать при обогреве» (FR-055):
        пока комнате нужен обогрев, она ниже уставки, и вентиляция стоит сама.

        Returns:
            Ничего.
        """
        guard = _guard("speed_within_limits")
        context = {
            **DEFAULTS,
            "outside_temperature": -5.0,
            "temperature": 20.0,
            "climate_setpoint": 22.5,
        }
        assert guard(None, context) is False
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "room_below_setpoint"
        )

    def test_cold_room_does_not_stop_exhaust(self) -> None:
        """Вытяжку санузла правило по уставке не гасит: сушат не ради тепла.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {
            "ventilation_role": "exhaust",
            "temperature": 26.0,
            "climate_setpoint": 30.0,
        }
        assert guard(None, context) is True


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


class TestCommandsCarryOnlyOwnFields:
    """В команду едет ровно то, что принимает её услуга (боевой дефект 2026-10-12).

    Контекст перехода накопительный и хранит и ``preset_mode``, и ``percentage``.
    Если действие кладёт в данные оба поля, Home Assistant отвергает команду
    целиком с ``400 Bad Request``: ``fan.set_preset_mode`` с лишним
    ``percentage`` не применялся вовсе, и рекуператор оставался в прежнем режиме,
    пока платформа считала, что переключила его.
    """

    def test_set_preset_sends_only_preset_mode(self) -> None:
        """У команды режима нет чужого поля ``percentage``.

        Returns:
            Ничего.
        """
        intent = _action("fan_set_preset")(
            None,
            {
                "entity_id": "fan.base_smart",
                "preset_mode": "Рекуперация (зима)",
                "percentage": 43,
            },
        )
        assert intent is not None
        assert set(intent.data) == {"preset_mode"}, (
            f"в данных команды режима {sorted(intent.data)}: лишний ключ означает "
            "400 и потерю команды — режим не переключится"
        )

    def test_set_percentage_sends_only_percentage(self) -> None:
        """У команды скорости нет чужого поля ``preset_mode``.

        Returns:
            Ничего.
        """
        intent = _action("fan_set_percentage")(
            None,
            {"entity_id": "fan.base_smart", "preset_mode": "Приток MAX", "percentage": 43},
        )
        assert intent is not None
        assert set(intent.data) == {"percentage"}

    def test_turn_off_sends_no_data(self) -> None:
        """``fan.turn_off`` уходит без данных, даже если процент в контексте.

        Returns:
            Ничего.
        """
        intent = _action("fan_turn_off")(
            None,
            {"entity_id": "fan.base_smart", "percentage": 100, "preset_mode": "Приток MAX"},
        )
        assert intent is not None
        assert intent.data == {}, (
            f"в команду выключения ушло {intent.data!r}: лишний ключ роняет её "
            "с 400, и прибор остаётся работать"
        )

    def test_airing_on_sends_only_preset_mode(self) -> None:
        """Проветривание уходит одним режимом, без накопленного процента.

        Returns:
            Ничего.
        """
        intent = _action("fan_airing_on")(
            None,
            {"entity_id": "fan.base_smart", "mode_airing": "Приток MAX", "percentage": 43},
        )
        assert intent is not None
        assert set(intent.data) == {"preset_mode"}

    def test_exhaust_on_sends_no_data(self) -> None:
        """Вытяжке данные не нужны, даже если в контексте есть чужие поля.

        Returns:
            Ничего.
        """
        intent = _action("exhaust_on")(
            None, {"entity_id": "fan.vytyazhka", "percentage": 50, "preset_mode": "Приток"}
        )
        assert intent is not None
        assert intent.data == {}


class TestAiringOn:
    """Проветривание ставит режим из своего параметра (T085)."""

    def test_airing_on_sends_mode_airing(self) -> None:
        """Действие берёт режим из ``mode_airing``, а не из накопленного.

        Returns:
            Ничего.
        """
        intent = _action("fan_airing_on")(
            None, {"entity_id": "fan.base_smart", "mode_airing": "Приток MAX"}
        )
        assert intent is not None
        assert (intent.domain, intent.service) == ("fan", "set_preset_mode")
        assert intent.data == {"preset_mode": "Приток MAX"}

    def test_airing_on_without_mode_is_silent(self) -> None:
        """Параметра режима нет — команды нет, но и выдумки нет.

        Returns:
            Ничего.
        """
        assert _action("fan_airing_on")(None, {"entity_id": "fan.base_smart"}) is None


class TestModifierReset:
    """Автосброс модификаторов владельца (T085)."""

    def test_airing_after_timeout_restores_mode_and_clears_modifier(self) -> None:
        """По таймеру: режим, скорость, затем снятие модификатора.

        Returns:
            Ничего.
        """
        steps = _steps(
            _action("airing_after_timeout")(
                None,
                {
                    "entity_id": "fan.base_smart",
                    "chosen_mode": "Рекуперация (зима)",
                    "percentage": 43,
                    "airing_entity": "input_boolean.provetrivanie",
                },
            )
        )
        assert [step.service for step in steps] == [
            "set_preset_mode",
            "set_percentage",
            "turn_off",
        ]
        assert steps[-1].domain == "input_boolean"
        assert steps[-1].device_id == "input_boolean.provetrivanie"

    def test_exhaust_after_timeout_turns_off_and_clears_modifier(self) -> None:
        """По таймеру вытяжка гаснет, затем снимается модификатор.

        Returns:
            Ничего.
        """
        steps = _steps(
            _action("exhaust_after_timeout")(
                None,
                {
                    "entity_id": "fan.vytyazhka",
                    "exhaust_entity": "input_boolean.provetrivanie_vytyazhka",
                },
            )
        )
        assert [(step.domain, step.service) for step in steps] == [
            ("fan", "turn_off"),
            ("input_boolean", "turn_off"),
        ]

    def test_airing_off_turns_off_and_clears_modifier(self) -> None:
        """Запасной путь проветривания: гасит прибор и снимает модификатор.

        Returns:
            Ничего.
        """
        steps = _steps(
            _action("airing_off")(
                None,
                {
                    "entity_id": "fan.base_smart",
                    "airing_entity": "input_boolean.provetrivanie",
                },
            )
        )
        assert [(step.domain, step.service) for step in steps] == [
            ("fan", "turn_off"),
            ("input_boolean", "turn_off"),
        ]


class TestExhaustByBathroom:
    """Вытяжка санузла по температуре и/или влажности (T086)."""

    def test_should_run_exhaust_on_hot_bathroom(self) -> None:
        """Санузел выше порога температуры — вытяжку включаем.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {"ventilation_role": "exhaust", "temperature": 26.0}
        assert guard(None, context) is True

    def test_should_run_exhaust_on_wet_bathroom(self) -> None:
        """Санузел влажнее порога — вытяжку включаем.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {"ventilation_role": "exhaust", "humidity": 70.0}
        assert guard(None, context) is True

    def test_should_run_exhaust_on_owner_modifier(self) -> None:
        """Модификатор владельца включает вытяжку без показаний санузла.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {"ventilation_role": "exhaust", "exhaust_on": True}
        assert guard(None, context) is True

    def test_should_run_exhaust_denies_comfortable_bathroom(self) -> None:
        """Санузел сух и не перегрет — причина названа, вытяжка не нужна.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {"ventilation_role": "exhaust", "temperature": 23.0, "humidity": 50.0}
        assert guard(None, context) is False
        assert getattr(guard, "deny_reason", lambda *_: None)(None, context) == (
            "bathroom_comfortable"
        )

    def test_should_run_exhaust_ignores_recuperator_role(self) -> None:
        """Рекуператор (supply) вытяжкой не управляет.

        Returns:
            Ничего.
        """
        guard = _guard("should_run_exhaust")
        context = {"ventilation_role": "supply", "temperature": 30.0, "exhaust_on": True}
        assert guard(None, context) is False

    def test_exhaust_should_stop_when_done(self) -> None:
        """Модификатор снят и санузел в норме — вытяжку пора гасить.

        Returns:
            Ничего.
        """
        guard = _guard("exhaust_should_stop")
        context = {"ventilation_role": "exhaust", "temperature": 23.0, "humidity": 50.0}
        assert guard(None, context) is True

    def test_exhaust_should_keep_running_while_modifier_on(self) -> None:
        """Пока модификатор включён, вытяжка не гаснет.

        Returns:
            Ничего.
        """
        guard = _guard("exhaust_should_stop")
        context = {"ventilation_role": "exhaust", "exhaust_on": True}
        assert guard(None, context) is False
