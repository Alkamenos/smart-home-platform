"""Движение сразу после нашего выключения — эхо датчика, а не человек (2026-10-14).

Боевой случай: фонари сада (`light.vse_fonari`) включались по движению, а
датчиком движения там служит **общая тревога камеры** (`kalitka_sad_lc_motion_alarm`
— у неё нет детектора «человек»). Камера видит смену освещённости: платформа
гасит фонари, через секунду приходит «движение», и фонари зажигаются снова —
свет мигал, а «свет по движению» превращался в «горит всю ночь».

Тест держит защиту: пока состояние автомата только что вошло в «выключено»
(свет погасили мы сами), движение не включает свет и отказ назван `motion_echo`.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.guards.builtin import DEFAULT_MOTION_ECHO_SEC, make_may_turn_on


ROOM = "sad"


def _guard(monotonic_value: float = 100.0) -> Any:
    """Условие включения света с управляемым временем.

    Args:
        monotonic_value: Монотонное «сейчас» для проверки окна эха.

    Returns:
        Функция (state, context) -> bool.
    """
    return make_may_turn_on(
        now=lambda context: datetime(2026, 10, 14, 21, 0, tzinfo=ZoneInfo("Asia/Yekaterinburg")),
        monotonic=lambda: monotonic_value,
    )


def _context(**params: Any) -> dict[str, Any]:
    """Контекст перехода включения света.

    Args:
        **params: Прочие ключи контекста.

    Returns:
        Словарь контекста: комната, флаги дома, темнота.
    """
    return {
        "room": ROOM,
        "sleep_modifier_on": False,
        "daylight": False,
        "time_zone": "Asia/Yekaterinburg",
        **params,
    }


def _state(entered_at: float) -> Any:
    """Состояние автомата во время входа в «выключено».

    Args:
        entered_at: Монотонное время входа в состояние.

    Returns:
        Состояние-двойник.
    """
    return SimpleNamespace(current_state="OFF", entered_at=entered_at, context={})


def test_motion_just_after_our_switch_off_does_not_turn_light_on() -> None:
    """Через секунду после нашего выключения свет не включается."""
    guard = _guard(monotonic_value=100.0)

    assert guard(_state(entered_at=99.0), _context()) is False


def test_motion_is_echo_is_named() -> None:
    """Отказ назван `motion_echo`, а не безликим «условие не прошло»."""
    guard = _guard(monotonic_value=100.0)

    assert guard.deny_reason(_state(entered_at=99.0), _context()) == "motion_echo"


def test_later_motion_turns_light_on() -> None:
    """Через окно эха движение снова считается движением человека."""
    guard = _guard(monotonic_value=100.0)

    assert guard(_state(entered_at=100.0 - DEFAULT_MOTION_ECHO_SEC - 1), _context()) is True


def test_echo_window_can_be_disabled_by_param() -> None:
    """Параметр `motion_echo_sec: 0` выключает правило."""
    guard = _guard(monotonic_value=100.0)

    assert guard(_state(entered_at=99.0), _context(motion_echo_sec=0)) is True


def test_unknown_entered_at_is_not_an_echo() -> None:
    """Без времени входа правило не выдумывает эхо."""
    guard = _guard(monotonic_value=100.0)

    assert guard(SimpleNamespace(current_state="OFF", entered_at=None, context={}), _context())
    assert guard(None, _context()) is True


def test_sleeping_still_wins_over_echo() -> None:
    """Спящий дом — отдельная причина отказа, и она тоже запрещает свет."""
    guard = _guard(monotonic_value=100.0)

    assert guard(_state(entered_at=0.0), _context(sleep_modifier_on=True)) is False
    assert guard.deny_reason(_state(entered_at=0.0), _context(sleep_modifier_on=True)) == (
        "sleep_modifier"
    )


@pytest.mark.parametrize("window", [1.0, 5.0, 30.0])
def test_window_boundary_is_inclusive(window: float) -> None:
    """Граница окна включительна: ровно на границе движение ещё эхо."""
    guard = _guard(monotonic_value=100.0)

    assert guard(_state(entered_at=100.0 - window), _context(motion_echo_sec=window)) is False
