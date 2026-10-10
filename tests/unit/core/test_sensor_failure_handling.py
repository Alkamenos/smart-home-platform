"""Отказ датчика: решение не принимается, причина называется (US5).

Поведение при отказе задаётся заранее, а не определяется тем, как упадёт код.
Боевой случай 2026-10-10: сенузел и контейнер без окон, и если датчик там молчит,
единственный способ согреть комнату — электрический. Молчание датчика не должно
превращаться в «достаточно тепло».

Проверяется различение, которое движок уже умеет: «данных нет» и «значение не
подходит» — разные причины (`engine.py:761-806`). Условие климата обязано
пользоваться этим, а не заводить свои коды.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

import pytest

from core.guards.builtin import build_guards, make_humidity_above


def _may_heat() -> Any:
    """Условие включения обогрева.

    Returns:
        Функция (state, context) -> bool.
    """
    return build_guards(control_tracker=None)["may_heat"]


def _ctx(temperature: Any = None, **params: Any) -> dict[str, Any]:
    """Контекст перехода климата.

    Args:
        temperature: Показание датчика; ``None`` означает «ключа нет».
        **params: Прочие ключи.

    Returns:
        Словарь контекста.
    """
    context: dict[str, Any] = {"room": "sanuzel", "sleep_modifier_on": False}
    if temperature is not None:
        context["temperature"] = temperature
    context.update(params)
    return context


class TestUnreadableValueIsMissingData:
    """Нечитаемое показание равно отсутствию данных, а не значению."""

    @pytest.mark.parametrize(
        "value",
        [
            "unavailable",
            "unknown",
            "",
            "   ",
            "nan",
            None,
        ],
    )
    def test_unreadable_never_allows_heating(self, value: Any) -> None:
        """Молчащий датчик не включает обогрев.

        Args:
            value: Непригодное показание.

        Returns:
            Ничего.
        """
        guard = _may_heat()

        assert guard(None, _ctx(value, climate_setpoint=21.0)) is False, (
            f"показание {value!r} означает «данных нет», а не «холодно»: "
            "обогрев по нему включаться не должен"
        )

    def test_unreadable_never_stops_heating(self) -> None:
        """Молчащий датчик не выключает обогреватель.

        Returns:
            Ничего.
        """
        guard = build_guards(control_tracker=None)["may_stop_heating"]

        assert guard(None, _ctx("unavailable", climate_setpoint=21.0)) is False, (
            "без показания нельзя утверждать, что цель достигнута: выключение "
            "по догадке оставит комнату холодной"
        )

    def test_reason_is_data_missing_not_daylight(self) -> None:
        """Причина отказа — «данных нет», а не «светло».

        Returns:
            Ничего.
        """
        guard = _may_heat()

        reason = guard.deny_reason(None, _ctx("unavailable", climate_setpoint=21.0))

        assert reason == "guard_data_missing", (
            f"«данных нет» и «значение не подходит» в журнале означают разное: "
            f"первое — сбой датчика, второе — штатная работа. Получено {reason!r}"
        )

    def test_deny_reason_never_names_daylight_for_missing_data(self) -> None:
        """Отказ по отсутствию данных никогда не называется «светло».

        Returns:
            Ничего.
        """
        guard = _may_heat()

        reasons = {
            guard.deny_reason(None, _ctx(value, climate_setpoint=21.0))
            for value in ("unavailable", "unknown", "", None)
        }

        assert "daylight" not in reasons, (
            f"причина «светло» при отсутствии данных уводит в сторону солнца, "
            f"а проблема в датчике: {reasons}"
        )


class TestHumiditySameRule:
    """Правило одинаково для влажности: нет данных — нет решения."""

    @pytest.mark.parametrize("value", ["unavailable", "unknown", "", None])
    def test_unreadable_humidity_never_turns_on(self, value: Any) -> None:
        """Молчащий датчик влажности не включает вентиляцию.

        Args:
            value: Непригодное показание.

        Returns:
            Ничего.
        """
        guard = make_humidity_above()

        assert guard(None, {"humidity": value, "humidity_threshold": 60}) is False


class TestGuardsDeclareRequiredData:
    """Условия объявляют нужные данные, иначе отказ приходит не оттуда."""

    def test_climate_guards_declare_temperature(self) -> None:
        """Климатические условия объявляют показание.

        Объявление навешивается на зарегистрированную функцию
        (``with_requirements`` в ``build_guards``), а не на результат фабрики:
        проверять надо тот объект, который движок действительно вызывает.

        Returns:
            Ничего.
        """
        guards = build_guards(control_tracker=None)

        assert guards["may_heat"].requires == ("temperature",)
        assert guards["may_stop_heating"].requires == ("temperature",)

    def test_setpoint_is_never_declared_as_measurement(self) -> None:
        """Уставку объявлять нельзя: любое число прошло бы как измерение.

        Returns:
            Ничего.
        """
        guards = build_guards(control_tracker=None)

        assert "climate_setpoint" not in guards["may_heat"].requires, (
            "уставка проверяется на допустимость внутри условия: объявив её "
            "требуемой, движок вернул бы «данных нет» прежде, чем условие сказало "
            "бы «уставка вне диапазона»"
        )

    def test_humidity_guards_declare_measurement(self) -> None:
        """Влажность объявляется: так уже было.

        Returns:
            Ничего.
        """
        guards = build_guards(control_tracker=None)

        assert guards["humidity_above_60"].requires == ("humidity",)
        assert guards["humidity_below_60"].requires == ("humidity",)


class TestSetpointOutOfRange:
    """Уставка вне диапазона — отказ, а не запасное значение."""

    def test_absurd_setpoint_denied(self) -> None:
        """Уставка 95 градусов отвергается.

        Returns:
            Ничего.
        """
        guard = _may_heat()

        ctx = _ctx(19.0, climate_setpoint=95.0, setpoint_min=5.0, setpoint_max=30.0)

        assert guard(None, ctx) is False, (
            "уставка вне диапазона — это «уставка негодна»: греть по ней значит "
            "перегреть дом, а молча подставить 30 — значит не сказать, что не так"
        )

    def test_absurd_setpoint_has_own_reason(self) -> None:
        """Причина называет уставку, а не данные.

        Returns:
            Ничего.
        """
        guard = _may_heat()

        reason = guard.deny_reason(
            None,
            _ctx(19.0, climate_setpoint=95.0, setpoint_min=5.0, setpoint_max=30.0),
        )

        assert reason == "setpoint_unavailable"
