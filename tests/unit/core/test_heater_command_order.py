"""Проверки порядка команд обогревателю: сначала включить, потом таймер.

Знание владельца, проверенное в доме 2026-10-11: обогреватель принимает таймер
**только если уже включён**. Проверено вручную:

- ``number.set_value = 900`` на выключенном приборе → таймер принят,
  обогреватель **off** (то есть не греет);
- включить прибор руками, затем ``number.set_value = 7000`` → обогреватель
  **on** и греет.

Значит, порядок обязателен: ``switch.turn_on`` → убедиться, что прибор
включился → ``number.set_value``. Прежняя реализация слала только таймер, и
обогрев выглядел исправным, не работая: автомат переходил в ``HEATING``, таймер
в Home Assistant обновлялся, сторож писал ``ok`` — а комната была холодная.

Класс дефекта тот же, что спека 010 US1 описывала как главный: механизм есть,
выглядит исправным, а команда до прибора не доходит.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


RUN_MINUTES = 15
RUN_SECONDS = RUN_MINUTES * 60

HEATER = "switch.obogrevatel_spalnia"
TIMER = "number.obogrevatel_spalnia_countdown"


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция (state, context) -> результат.

    Raises:
        AssertionError: действия нет в реестре.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: в реестре {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


class TestHeaterIsSwitchedOnBeforeTheTimer:
    """Порядок команд: прибор включается, и только потом получает таймер."""

    def test_command_carries_both_steps_in_order(self) -> None:
        """Команда описывает два шага: включение, затем таймер.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        result = action(
            None,
            {
                "entity_id": HEATER,
                "heater_timer": TIMER,
                "run_minutes": RUN_MINUTES,
                "timer_unit": "s",
            },
        )

        steps = _steps(result)
        assert len(steps) == 2, (
            f"команда описывает {len(steps)} шагов вместо двух: прибор сначала "
            "должен включиться, и только потом принять таймер — иначе таймер "
            "записывается в выключенный обогреватель и ничего не греет"
        )
        assert (steps[0].domain, steps[0].service, steps[0].device_id) == (
            "switch",
            "turn_on",
            HEATER,
        ), f"первым шагом должно быть включение прибора, а не {steps[0]!r}"
        assert (steps[1].domain, steps[1].service, steps[1].device_id) == (
            "number",
            "set_value",
            TIMER,
        ), f"вторым шагом должен идти таймер, а не {steps[1]!r}"
        assert steps[1].data["value"] == RUN_SECONDS, (
            f"в таймер ушло {steps[1].data.get('value')!r} вместо {RUN_SECONDS} "
            "секунд: таймер измеряется в секундах"
        )

    def test_second_step_waits_for_confirmation(self) -> None:
        """Таймер ставится только после подтверждения, что прибор включился.

        Без проверки платформа отправляет таймер вслепую: прибор может не
        включиться (обрыв, занятость, сбой), и запись будет молча игнорирована —
        ровно тот случай, что наблюдался в доме.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        result = action(
            None,
            {
                "entity_id": HEATER,
                "heater_timer": TIMER,
                "run_minutes": RUN_MINUTES,
                "timer_unit": "s",
            },
        )

        steps = _steps(result)
        assert getattr(steps[1], "requires_state", None) == "on", (
            "второй шаг не ждёт подтверждения включения: без него таймер "
            "уходит вслепую и может быть принят на выключенном приборе"
        )


class TestHeaterWithoutTimerStillSwitchesOn:
    """Дома без таймера прибор всё равно нужно включать."""

    def test_single_turn_on_step(self) -> None:
        """Без таймера остаётся одно действие — включение.

        Returns:
            Ничего.
        """
        action = _action("heater_timer_on")

        result = action(
            None,
            {"entity_id": HEATER, "run_minutes": RUN_MINUTES},
        )

        steps = _steps(result)
        assert len(steps) == 1, (
            f"без таймера ожидалась одна команда включения, получено {len(steps)}"
        )
        assert steps[0].domain == "switch"


class TestTurningOffDropsTheTimerFirst:
    """Выключение: сначала обнулить таймер, иначе прибор может загореться снова."""

    def test_off_command_zeroes_timer_before_switching_off(self) -> None:
        """Порядок выключения: таймер в ноль, затем прибор выключить.

        Returns:
            Ничего.
        """
        action = _action("heater_off")

        result = action(
            None,
            {"entity_id": HEATER, "heater_timer": TIMER},
        )

        steps = _steps(result)
        assert len(steps) == 2, (
            f"выключение описывает {len(steps)} шагов вместо двух: таймер, "
            "оставленный на выключенном приборе, включит его позже — "
            "обогреватель загорается сам через несколько минут"
        )
        assert (steps[0].domain, steps[0].device_id) == ("number", TIMER)
        assert steps[0].data["value"] == 0, f"в таймер ушло {steps[0].data.get('value')!r} вместо 0"
        assert (steps[1].domain, steps[1].service, steps[1].device_id) == (
            "switch",
            "turn_off",
            HEATER,
        )

    def test_off_command_without_timer_is_single_step(self) -> None:
        """Без таймера выключение остаётся одной командой.

        Returns:
            Ничего.
        """
        action = _action("heater_off")

        result = action(None, {"entity_id": HEATER})

        steps = _steps(result)
        assert len(steps) == 1
        assert steps[0].domain == "switch"


def _steps(result: Any) -> list[Any]:
    """Привести результат действия к списку шагов команды.

    Действие обязано возвращать список намерений: пока оно возвращало одно,
    порядок «включить, потом поставить таймер» был невыразим в принципе.

    Args:
        result: То, что вернуло действие.

    Returns:
        Список шагов.
    """
    assert isinstance(result, list), (
        f"действие вернуло {type(result).__name__}, а не список шагов: "
        "обогревателю нужны две команды подряд, а одна команда места для "
        "порядка не оставляет"
    )
    return result
