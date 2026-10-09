"""Проверки условий климата: когда можно греть, когда нельзя.

Требования владельца (спека 011, сценарии US1):

- Дом держит заданную температуру: обогреватель включается, когда в комнате
  холоднее цели, и выключается, когда дошло до цели.
- **Ни одного молчаливого отказа.** Каждое «нет» сопровождается именем причины:
  «спим», «ночь», «светло», «данных нет», «выключено владельцем» — это пять
  разных ситуаций, и склейка их в `guard_failed` запрещена правилом владельца
  о логах (2026-10-09).

Здесь проверяется только решение «греть или нет». Команды — в
`test_climate_actions.py`, сквозной путь — в `tests/integration/climate/`.

Проверки падают до реализации: на момент написания функций
`below_setpoint`, `at_or_above_setpoint`, `climate_is_enabled`,
`managed_by_hardware_ok` в `core.guards.builtin` нет.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.guards.builtin import build_guards


SETPOINT = 22.0
HYSTERESIS = 0.5


def _guards() -> dict[str, Any]:
    """Собрать реестр условий.

    Время здесь не подменяется: климат о нём не решает. Сезон приходит из
    Home Assistant (`input_boolean.zima`), а «день/ночь» для обогрева не имеет
    значения — решение «холодно ли» принимает датчик комнаты, а не часы.

    Returns:
        Словарь «имя условия → функция (state, context) -> bool».
    """
    return build_guards(control_tracker=None)


def _ctx(temperature: Any, **params: Any) -> dict[str, Any]:
    """Контекст перехода климата.

    Args:
        temperature: Показание датчика комнаты. `None` — датчика нет вовсе,
            строка (например «unavailable») — датчик есть, но не отвечает.
        params: Прочие ключи контекста: уставка, гистерезис, флаги.

    Returns:
        Словарь контекста.
    """
    context: dict[str, Any] = {"room": "spalnia", "sleep_modifier_on": False}
    context.update(params)
    if temperature is not None:
        context["temperature"] = temperature
    return context


def _guard(name: str) -> Any:
    """Взять условие по имени.

    Args:
        name: Имя условия в реестре.

    Returns:
        Функция (state, context) -> bool с `deny_reason`.

    Raises:
        AssertionError: условия нет в реестре — значит оно не реализовано или
            не зарегистрировано, и шаблон его перехода отклонит молча.
    """
    guards = _guards()
    assert name in guards, (
        f"условие `{name}` не зарегистрировано: в реестре {sorted(guards)}. "
        "Условие вне реестра — переход отклоняется с ошибкой, и фича выглядит "
        "исправной, но не срабатывает никогда"
    )
    return guards[name]


class TestHeaterTurnsOnWhenColderThanSetpoint:
    """Включение разрешено, когда в комнате холоднее цели минус гистерезис."""

    def test_cold_room_allows_heating(self) -> None:
        """Комната на 1.5 °C ниже цели: обогреватель нужен.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(20.5, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is True, (
            f"{SETPOINT} цель, комната 20.5, гистерезис {HYSTERESIS} — обогревать надо, "
            "а условие запретило"
        )

    def test_edge_of_dead_zone_stays_off(self) -> None:
        """Ровно на нижней границе мёртвой зоны обогреватель ещё не нужен.

        Мёртвая зона — это `[цель − гистерезис, цель]`. Её нижняя граница
        принадлежит зоне, а не нагреву: обогреватель включается строго ниже неё.
        Иначе на границе платформа металась бы между «включить» и «не включать»
        из-за одного и того же показания датчика.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(SETPOINT - HYSTERESIS, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False, (
            "21.5 при цели 22 и гистерезисе 0.5 — это нижняя граница мёртвой зоны, "
            "а не холод: обогреватель на границе дрожал бы между решениями"
        )

    def test_just_below_the_edge_heats(self) -> None:
        """Чуть ниже границы — греть нужно.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(
            SETPOINT - HYSTERESIS - 0.1, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS
        )

        assert guard(None, context) is True, (
            "21.4 при цели 22 — за полградуса до цели, обогреватель нужен"
        )


class TestHeaterStaysOffInsideDeadZone:
    """В мёртвой зоне обогреватель не включается: иначе он будет дрожать."""

    def test_room_inside_dead_zone_denies(self) -> None:
        """Комната на 0.3 °C ниже цели — в мёртвой зоне.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(21.7, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False, (
            "21.7 при цели 22 и гистерезисе 0.5 — это мёртвая зона: обогреватель "
            "дёргался бы на каждом градусе"
        )

    def test_room_above_setpoint_denies(self) -> None:
        """Комната теплее цели — обогревать нечего.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(22.5, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False

    def test_default_hysteresis_is_half_degree(self) -> None:
        """Без заданного гистерезиса — 0.5 °C: узкая зона дрожит, широкая перегревает.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        assert guard(None, _ctx(21.6, climate_setpoint=SETPOINT)) is False, (
            "гистерезис по умолчанию должен быть 0.5 °C, а комната 21.6 при цели 22 в него попадает"
        )
        assert guard(None, _ctx(21.4, climate_setpoint=SETPOINT)) is True

    def test_at_or_above_setpoint_is_the_mirror(self) -> None:
        """Условие выключения — зеркало условия включения.

        Returns:
            Ничего.
        """
        guard = _guard("at_or_above_setpoint")

        assert guard(None, _ctx(22.0, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)) is True, (
            "достигнута цель — обогреватель выключается"
        )
        assert guard(None, _ctx(20.5, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)) is False


class TestNoDecisionWithoutData:
    """Нет данных — нет решения. Вслепую включать обогреватель опаснее, чем не включить."""

    def test_missing_sensor_denies(self) -> None:
        """Датчика нет в контексте вовсе.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(None, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False, (
            "без показания датчика «холодно» — это догадка, а решение принимается "
            "по данным: включение вслепую опасно"
        )
        assert guard.deny_reason(None, context) == "guard_data_missing"  # type: ignore[attr-defined]

    def test_unavailable_sensor_is_not_zero(self) -> None:
        """`unavailable` — это отсутствие данных, а не ноль градусов.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx("unavailable", climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False, (
            "«unavailable» не должно превращаться в 0 °C и выглядеть как «очень "
            "холодно»: молчаливый перегрев — худший исход"
        )
        assert guard.deny_reason(None, context) == "guard_data_missing"  # type: ignore[attr-defined]

    def test_missing_setpoint_denies(self) -> None:
        """Цели нет — решение принимать не о чем.

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        assert guard(None, _ctx(20.0, hysteresis=HYSTERESIS)) is False, (
            "без цели сравнивать нечего: включение «на всякий случай» — это "
            "перегрев с лишней электроэнергией"
        )
        assert guard.deny_reason(None, _ctx(20.0, hysteresis=HYSTERESIS)) == (  # type: ignore[attr-defined]
            "guard_data_missing"
        )

    def test_setpoint_out_of_range_is_named(self) -> None:
        """Цель вне диапазона — собственная причина, а не «данных нет».

        Returns:
            Ничего.
        """
        guard = _guard("below_setpoint")

        context = _ctx(20.0, climate_setpoint=95.0, hysteresis=HYSTERESIS)

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "setpoint_unavailable", (  # type: ignore[attr-defined]
            "уставка 95 °C — это поломка настройки, а не отсутствие данных: "
            "утром в журнале должно быть видно различие"
        )


class TestOwnerCanSwitchClimateOff:
    """Право владельца: одна кнопка в Home Assistant останавливает климат."""

    def test_feature_flag_on_allows(self) -> None:
        """Фиче-флаг включён — условие разрешает.

        Returns:
            Ничего.
        """
        guard = _guard("climate_is_enabled")

        assert guard(None, {"climate_enabled": True}) is True

    def test_feature_flag_off_denies_with_reason(self) -> None:
        """Фиче-флаг выключен — отказ с именем причины.

        Returns:
            Ничего.
        """
        guard = _guard("climate_is_enabled")

        context = {"climate_enabled": False}

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "climate_disabled"  # type: ignore[attr-defined]

    def test_missing_flag_is_not_a_blocker(self) -> None:
        """Нет фиче-флага в доме — климат всё равно работает.

        Returns:
            Ничего.
        """
        guard = _guard("climate_is_enabled")

        assert guard(None, {}) is True, (
            "в доме без фиче-флага климат должен работать: флаг — право "
            "владельца, а не условие работы"
        )


class TestHardwareThermostatRoomIsNotDriven:
    """В комнате со штатным термостатом платформа обогревателем не управляет."""

    def test_managed_room_denies_with_reason(self) -> None:
        """Комната отмечена как управляемая термостатом.

        Returns:
            Ничего.
        """
        guard = _guard("managed_by_hardware_ok")

        context = {"managed_by_hardware": True}

        assert guard(None, context) is False
        assert guard.deny_reason(None, context) == "managed_by_hardware"  # type: ignore[attr-defined]

    def test_ordinary_room_allows(self) -> None:
        """Обычная комната — можно управлять.

        Returns:
            Ничего.
        """
        guard = _guard("managed_by_hardware_ok")

        assert guard(None, {"managed_by_hardware": False}) is True
        assert guard(None, {}) is True


class TestEveryDenialIsNamed:
    """Правило владельца о логах: отказ без причины — дефект."""

    def test_no_client_guard_leaves_a_denial_unnamed(self) -> None:
        """Ни одно клиентское условие климата не возвращает отказ без причины.

        Returns:
            Ничего.
        """
        from core.events.fsm_events import GUARD_DENIAL_REASONS

        unnamed: list[str] = []
        cases: dict[str, list[dict[str, Any]]] = {
            "below_setpoint": [_ctx("unavailable", climate_setpoint=SETPOINT)],
            "at_or_above_setpoint": [_ctx("unavailable", climate_setpoint=SETPOINT)],
            "climate_is_enabled": [{"climate_enabled": False}],
            "managed_by_hardware_ok": [{"managed_by_hardware": True}],
        }
        for name, contexts in cases.items():
            guard = _guard(name)
            for context in contexts:
                if guard(None, context) is False:
                    reason = guard.deny_reason(None, context)  # type: ignore[attr-defined]
                    if reason is None:
                        unnamed.append(f"{name}: {context}")
                    elif reason not in GUARD_DENIAL_REASONS:
                        unnamed.append(f"{name}: причина `{reason}` вне реестра")

        assert not unnamed, f"отказ без названной причины: {unnamed}"

    def test_conditional_refusal_falls_back_to_guard_failed(self) -> None:
        """Отказ «условие штатно не выполнено» остаётся без особой причины.

        Это не дефект и не «молчание»: движок в этом случае пишет
        ``guard_failed`` — условие просто не выполнилось, и называть это чем-то
        конкретным было бы враньём. Особые причины обязаны называться там, где
        отказ означает **поломку или запрет владельца** (данных нет, уставка
        негодна, климат выключен, комната отдана термостату) — это проверяет
        проверка выше.

        Returns:
            Ничего.
        """
        guard = _guard("at_or_above_setpoint")

        context = _ctx(20.0, climate_setpoint=SETPOINT, hysteresis=HYSTERESIS)

        assert guard(None, context) is False, "в комнате холодно — выключать обогреватель рано"
        assert guard.deny_reason(None, context) is None, (  # type: ignore[attr-defined]
            "отказ «ещё нужно греть» не должен выдавать себя за поломку данных: "
            "движок напишет guard_failed, и это правда"
        )
