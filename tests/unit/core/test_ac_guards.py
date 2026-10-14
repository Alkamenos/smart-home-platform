"""Кондиционер: можно ли включать (FR-013, FR-014).

Три запрета, каждый из которых в доме уже стоит нажатием кнопки. Зимой
кондиционер включать нельзя — это портит технику; гейт
`ispolzovat_konditsioner` означает, что разрешения владельца нет; выше потолка
комфорта охлаждать нечего.

Порядок проверок по цене ошибки: право владельца (выключалка и гейт) важнее
сезона, а сезон важнее замера. Иначе в самую холодную погоду кондиционер
включился бы там, где владелец его запретил.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from core.guards.builtin import build_guards


COMFORT = 25.0


def _may_cool() -> Any:
    """Условие «кондиционер можно включать».

    Returns:
        Функция (state, context) -> bool.
    """
    return build_guards(control_tracker=None)["may_cool"]


def _ctx(temperature: Any = 27.0, **params: Any) -> dict[str, Any]:
    """Контекст перехода охлаждения.

    Args:
        temperature: Показание датчика комнаты.
        **params: Сезон, гейт, потолок комфорта.

    Returns:
        Словарь контекста.
    """
    context: dict[str, Any] = {"room": "gostinaia", "sleep_modifier_on": False, "cooling": True}
    if temperature is not None:
        context["temperature"] = temperature
    context.update(params)
    return context


class TestCoolingAllowed:
    """Охлаждение разрешено, когда лето, гейт есть и комната жаркая."""

    def test_hot_summer_allows_cooling(self) -> None:
        """Жарко, лето, разрешение есть — включаем.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(27.0, is_winter=False, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is True

    def test_just_above_ceiling_allows_cooling(self) -> None:
        """Чуть выше потолка — уже жарко.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(COMFORT + 0.1, is_winter=False, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is True

    def test_at_ceiling_does_not_cool(self) -> None:
        """Ровно потолок — ещё не жарко.

        Потолок определён как «выше него жарко», поэтому равенство означает
        «мера не требуется». Полградуса погоды не стоят работы кондиционера.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(COMFORT, is_winter=False, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is False


class TestCoolingNotApplicable:
    """Обогреватель не охлаждает: переход к нему не относится (B66)."""

    def test_heater_without_cooling_param_is_not_applicable(self) -> None:
        """Без параметра `cooling` прибор считается обогревателем.

        Returns:
            Ничего.
        """
        guard = _may_cool()
        context = _ctx(30.0, is_winter=False, ac_allowed=True, comfort_max=COMFORT)
        context.pop("cooling")

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "not_applicable"

    def test_conditioner_with_flag_keeps_house_checks(self) -> None:
        """У кондиционера запрет владельца остаётся своим именем, а не «не относится».

        Returns:
            Ничего.
        """
        guard = _may_cool()
        context = _ctx(30.0, is_winter=False, ac_allowed=False, comfort_max=COMFORT)

        assert guard.deny_reason(None, context) == "ac_not_allowed"


class TestWinterForbids:
    """Зимой кондиционер не включается никогда (FR-014)."""

    def test_winter_denies(self) -> None:
        """Зима запрещает охлаждение.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(30.0, is_winter=True, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is False, (
            "зимой кондиционер включать нельзя: это портит технику, и владелец "
            "выключал его с пульта с предупреждением"
        )

    def test_winter_reason_named(self) -> None:
        """Причина называет зиму, а не «нечем объяснить».

        Returns:
            Ничего.
        """
        guard = _may_cool()

        reason = guard.deny_reason(
            None, _ctx(30.0, is_winter=True, ac_allowed=True, comfort_max=COMFORT)
        )

        assert reason == "ac_forbidden_in_winter"

    def test_unknown_season_denies(self) -> None:
        """Неизвестный сезон запрещает: худее включить зимой, чем летом не охладить.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(30.0, is_winter=None, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is False, (
            "непрочитанный сезон не значит «не зима»: единственная цена ошибки "
            "в том, что техника пострадает зимой"
        )


class TestOwnerGate:
    """Гейт владельца выше сезона (FR-013)."""

    def test_gate_off_denies(self) -> None:
        """Гейт выключен — охлаждения нет.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(30.0, is_winter=False, ac_allowed=False, comfort_max=COMFORT)

        assert guard(None, ctx) is False

    def test_gate_reason_named(self) -> None:
        """Причина называет гейт.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        reason = guard.deny_reason(
            None, _ctx(30.0, is_winter=False, ac_allowed=False, comfort_max=COMFORT)
        )

        assert reason == "ac_not_allowed"

    def test_owner_gate_beats_season(self) -> None:
        """Выключалка владельца важнее сезона.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        reason = guard.deny_reason(
            None, _ctx(30.0, is_winter=True, ac_allowed=False, comfort_max=COMFORT)
        )

        assert reason == "ac_not_allowed", (
            f"первой по цене ошибки идёт право владельца, получено {reason!r}"
        )


class TestComfortCeiling:
    """Выше потолка комфорта охлаждать нечего."""

    def test_below_ceiling_denies(self) -> None:
        """Комната не догрета до потолка — не охлаждаем.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(23.0, is_winter=False, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is False, (
            "охлаждать прохладную комнату незачем: это лишние деньги и сквозняк"
        )

    def test_below_ceiling_reason_named(self) -> None:
        """Причина называет потолок комфорта.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        reason = guard.deny_reason(
            None, _ctx(23.0, is_winter=False, ac_allowed=True, comfort_max=COMFORT)
        )

        assert reason == "not_above_comfort"

    def test_unknown_ceiling_denies(self) -> None:
        """Непрочитанный потолок запрещает охлаждение.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx(30.0, is_winter=False, ac_allowed=True, comfort_max=None)

        assert guard(None, ctx) is False


class TestMissingData:
    """Нет данных — нет решения."""

    def test_missing_sensor_denies(self) -> None:
        """Молчащий датчик не включает кондиционер.

        Returns:
            Ничего.
        """
        guard = _may_cool()

        ctx = _ctx("unavailable", is_winter=False, ac_allowed=True, comfort_max=COMFORT)

        assert guard(None, ctx) is False

    def test_missing_sensor_reason_named(self) -> None:
        """Причина — «данных нет».

        Returns:
            Ничего.
        """
        guard = _may_cool()

        reason = guard.deny_reason(
            None, _ctx("unavailable", is_winter=False, ac_allowed=True, comfort_max=COMFORT)
        )

        assert reason == "guard_data_missing"

    def test_guard_declares_required_data(self) -> None:
        """Условие объявляет показание.

        Returns:
            Ничего.
        """
        guards = build_guards(control_tracker=None)

        assert guards["may_cool"].requires == ("temperature",)
