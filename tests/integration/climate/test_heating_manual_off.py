"""Ручное выключение обогревателя и срок страховочного таймера (B12/08.11).

Живая находка 2026-11-08: в гостевой спальне обогреватель выключили физически,
а автомат остался в HEATING. Сторож каждую минуту писал расхождение
``device_off_decision_on``, из HEATING не было пути назад к включению, а
страховочный таймер не срабатывал, потому что само-переход ``HEATING → HEATING``
заново его взводил.

Решение владельца: уважать ручное выключение 60 минут, затем снова греть.
Состояние ``OFF_MANUAL`` держит прибор выключенным, сторож не считает это
проблемой, а по истечении срока ручной блокировки автомат возвращается в IDLE и
следующее холодное показание снова включает обогрев.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from pathlib import Path

import yaml


TEMPLATE = Path("src/features/climate_control.yaml")


def _template() -> dict:
    """Разобрать шаблон климата.

    Returns:
        Содержимое YAML.
    """
    return yaml.safe_load(TEMPLATE.read_text(encoding="utf-8"))


def test_manual_switch_off_should_lead_to_manual_state() -> None:
    """Физическое выключение уводит автомат из HEATING в OFF_MANUAL."""
    pairs = {
        (transition["from_state"], transition["trigger"]): transition.get("to_state")
        for transition in _template()["transitions"]
    }

    assert pairs.get(("HEATING", "manual_switch_off")) == "OFF_MANUAL"


def test_manual_state_should_end_after_lockout() -> None:
    """Из OFF_MANUAL есть возврат по сроку ручной блокировки."""
    transitions = _template()["transitions"]
    back = [
        transition
        for transition in transitions
        if transition["from_state"] == "OFF_MANUAL" and transition["trigger"] == "timeout"
    ]

    assert back, "из ручного состояния нет возврата: обогрев не возобновится"
    assert back[0].get("timeout_param") == "manual_lockout_min"


def test_manual_state_is_declared() -> None:
    """Состояние обязано быть объявлено, иначе переход отклоняется."""
    assert "OFF_MANUAL" in _template()["states"]


def test_heating_self_transition_should_not_extend_safety_timeout() -> None:
    """Показание в полосе гистерезиса не отодвигает страховочное выключение."""
    self_transitions = [
        transition
        for transition in _template()["transitions"]
        if transition["from_state"] == "HEATING" and transition.get("to_state") == "HEATING"
    ]

    assert self_transitions, (
        "нет само-перехода HEATING → HEATING: показания в полосе станут отказами"
    )
    assert self_transitions[0].get("extends_timeout") is False


def test_heating_timeout_should_follow_run_minutes() -> None:
    """Срок автомата берётся из run_minutes, а не расходится с таймером розетки."""
    timeout = next(
        transition
        for transition in _template()["transitions"]
        if transition.get("trigger") == "timeout" and transition["from_state"] == "HEATING"
    )

    assert timeout.get("timeout_param") == "run_minutes"
    assert timeout.get("timeout_sec") == 900.0, "значение по умолчанию остаётся 15 минут"
