"""Страховка обогрева по таймеру: при отказе датчика прибор обязан погаснуть.

Живой дефект 2026-10-11: масляный радиатор простоял включённым **пять часов**
при истёкшем таймере. Журнал показал почему:

1. Страховочный таймер автомата отработал — переход ``HEATING → IDLE`` по
   ``timeout`` состоялся.
2. Выключение прибора было заблокировано ручным вмешательством
   (``manual lockout active``).
3. Датчик комнаты перестал присылать показания, поэтому нового решения не
   принял никто, и прибор грел до следующего вмешательства человека.

То есть защита FR-004 («включить на 15 минут, чтобы при отказе датчика не
остаться с открытым обогревом») **не работала**: страховкой считался таймер
прибора, а он обогрев не гасит.

Здесь две независимые проверки:

- шаг выключения не должен требовать состояния ``off`` — иначе команда
  не отправляется никогда (прибор уже выключен, чтобы его выключить);
- по таймеру прибор гасится принудительно, минуя блокировку: блокировка
  защищает «не мешай человеку», а не «дай прибору греть бесконечно».

Спека 014, T024 / FR-004.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from typing import Any

from core.action_handlers import ACTION_HANDLERS


HEATER = "switch.obogrevatel_spalnia"
TIMER = "number.obogrevatel_spalnia_countdown"


def _action(name: str) -> Any:
    """Взять действие по имени из реестра.

    Args:
        name: Имя действия.

    Returns:
        Функция (state, context) -> список шагов.

    Raises:
        AssertionError: действия нет в реестре — шаблон его не найдёт.
    """
    assert name in ACTION_HANDLERS, (
        f"действие `{name}` не зарегистрировано: в реестре {sorted(ACTION_HANDLERS)}"
    )
    return ACTION_HANDLERS[name]


class TestTurnOffIsNotGatedByItsOwnResult:
    """Команду выключения нельзя оборачивать требованием «уже выключен»."""

    def test_ordinary_off_has_no_state_requirement(self) -> None:
        """Обычное выключение не ждёт состояния ``off``.

        Returns:
            Ничего.
        """
        steps = _action("heater_off")(None, {"entity_id": HEATER, "heater_timer": TIMER})

        for step in steps:
            assert step.requires_state is None, (
                f"шаг {step.service} требует состояния {step.requires_state!r}: "
                "чтобы выключить прибор, он должен быть включён. Требование "
                "'выключен' делает команду неотправляемой — прибор, который "
                "и так off, провереку пройдёт, а включённый останется греться"
            )


class TestTimerExpiryIsAnEmergency:
    """Истечение страховочного таймера — аварийное выключение."""

    def test_emergency_off_exists(self) -> None:
        """В реестре есть отдельное аварийное выключение.

        Returns:
            Ничего.
        """
        assert "heater_emergency_off" in ACTION_HANDLERS, (
            "страховочного выключения нет в реестре: по истечении таймера "
            "используется обычное выключение, которое блокируется ручным "
            "вмешательством — в бою 2026-10-11 прибор так простоял пять часов"
        )

    def test_emergency_off_bypasses_manual_lockout(self) -> None:
        """Аварийное выключение обходит блокировку.

        Returns:
            Ничего.
        """
        steps = _action("heater_emergency_off")(
            None,
            {"entity_id": HEATER, "heater_timer": TIMER},
        )

        assert steps, "аварийное выключение не создало ни одной команды"
        for step in steps:
            assert step.bypass_lockout is True, (
                f"шаг {step.service} не обходит блокировку: человек коснулся "
                "прибора час назад, а обогреватель греет пятый час. Блокировка "
                "защищает от автоматики, а не от оставленного открытым обогрева"
            )

    def test_emergency_off_zeroes_timer_and_switches_off(self) -> None:
        """Порядок тот же: таймер в ноль, затем выключение прибора.

        Returns:
            Ничего.
        """
        steps = _action("heater_emergency_off")(None, {"entity_id": HEATER, "heater_timer": TIMER})

        assert len(steps) == 2, f"аварийное выключение описывает {len(steps)} шагов вместо двух"
        assert (steps[0].domain, steps[0].data["value"]) == ("number", 0), (
            "таймер не обнуляется первым: на выключенном приборе с таймером он "
            "включит обогрев позже сам"
        )
        assert (steps[1].domain, steps[1].service) == ("switch", "turn_off")

    def test_timer_step_carries_only_value(self) -> None:
        """В данные ``number.set_value`` не попадает ничего, кроме ``value``.

        Живая находка 01.11: шаг обнуления таймера нёс ещё и ``timer_unit``, и
        Home Assistant отверг вызов целиком: ``extra keys not allowed @
        data['timer_unit']``. Обнуление не прошло, а вместе с ним платформа
        пропустила и выключение прибора — обогреватель остался включённым.
        """
        steps = _action("heater_emergency_off")(None, {"entity_id": HEATER, "heater_timer": TIMER})

        assert steps[0].data == {"value": 0}, (
            f"в number.set_value уходят лишние поля: {steps[0].data}. Home Assistant "
            "принимает только value; лишний ключ уносит весь вызов"
        )

    def test_timer_step_is_best_effort_but_switch_is_required(self) -> None:
        """Сбой обнуления таймера не отменяет выключение прибора.

        Порядок «таймер, затем прибор» нужен, чтобы таймер не включил обогрев
        снова. Но если обнуление не удалось, выключение всё равно обязательно:
        оставить обогреватель включённым — худший из возможных исходов.
        """
        steps = _action("heater_emergency_off")(None, {"entity_id": HEATER, "heater_timer": TIMER})

        assert steps[0].best_effort is True, (
            "шаг обнуления таймера считается обязательным: его сбой снова "
            "отменит выключение обогревателя"
        )
        assert steps[1].best_effort is False, (
            "выключение прибора должно оставаться обязательным шагом"
        )


class TestTimeoutTransitionIsWiredToTheEmergencyAction:
    """Переход по таймеру ведёт в аварийное выключение."""

    def test_template_timeout_transition_uses_emergency_off(self) -> None:
        """В шаблоне переход ``HEATING → IDLE`` по ``timeout`` — аварийный.

        Returns:
            Ничего.
        """
        import pathlib

        import yaml

        template = yaml.safe_load(
            pathlib.Path("src/features/climate_control.yaml").read_text(encoding="utf-8")
        )
        timeout_transitions = [
            transition
            for transition in template["transitions"]
            if transition.get("trigger") == "timeout" and transition.get("from_state") == "HEATING"
        ]

        assert timeout_transitions, (
            "в шаблоне нет перехода по таймеру из HEATING: страховки нет, и при "
            "отказе датчика обогреватель останется включённым навсегда"
        )
        for transition in timeout_transitions:
            assert transition.get("action") == "heater_emergency_off", (
                f"переход по таймеру вызывает {transition.get('action')!r}: "
                "обычное выключение блокируется ручным вмешательством"
            )
