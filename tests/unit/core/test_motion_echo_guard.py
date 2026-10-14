"""Движение сразу после нашего выключения — эхо датчика, а не человек (2026-10-14).

Боевой случай: фонари сада (`light.vse_fonari`) включались по движению, а
датчиком движения там служит **общая тревога камеры** (`kalitka_sad_lc_motion_alarm`
— у неё нет детектора «человек»). Камера видит смену освещённости: платформа
гасит фонари, через секунду приходит «движение», и фонари зажигаются снова —
свет мигал, а «свет по движению» превращалось в «горит всю ночь» (боевые
переключения 20:46:12 и 20:56:42).

Признак эха — **наша команда выключения** (`light_off_at` в контексте состояния,
его ставит движок на действиях `turn_off_light`/`turn_off_night_light`), а не
вход в состояние «выключено»: в него ведут и переходы без действия (расписание,
«мы спим»), и по ним окно эха открываться не должно.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.guards.builtin import DEFAULT_MOTION_ECHO_SEC, make_may_turn_on


NOW = 1_800_000_000.0
ROOM = "sad"


def _guard(wall: float = NOW) -> Any:
    """Условие включения света с управляемым временем.

    Args:
        wall: Настенное «сейчас» — по нему считается окно эха.

    Returns:
        Функция (state, context) -> bool.
    """
    return make_may_turn_on(
        now=lambda context: datetime(2026, 10, 14, 21, 0, tzinfo=ZoneInfo("Asia/Yekaterinburg")),
        wall_clock=lambda: wall,
    )


def _context(**params: Any) -> dict[str, Any]:
    """Контекст перехода включения света.

    Args:
        **params: Прочие ключи контекста (в том числе `light_off_at`).

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


def test_motion_just_after_our_switch_off_does_not_turn_light_on() -> None:
    """Через секунду после нашего выключения свет не включается."""
    guard = _guard()

    assert guard(None, _context(light_off_at=NOW - 1.0)) is False


def test_motion_echo_is_named() -> None:
    """Отказ назван `motion_echo`, а не безликим «условие не прошло»."""
    guard = _guard()

    assert guard.deny_reason(None, _context(light_off_at=NOW - 1.0)) == "motion_echo"


def test_later_motion_turns_light_on() -> None:
    """Через окно эха движение снова считается движением человека."""
    guard = _guard()

    assert guard(None, _context(light_off_at=NOW - DEFAULT_MOTION_ECHO_SEC - 1)) is True


def test_echo_window_can_be_disabled_by_param() -> None:
    """Параметр `motion_echo_sec: 0` выключает правило."""
    guard = _guard()

    assert guard(None, _context(light_off_at=NOW - 1.0, motion_echo_sec=0)) is True


def test_without_our_switch_off_motion_is_not_echo() -> None:
    """Без нашей команды выключения правило не выдумывает эхо."""
    guard = _guard()

    assert guard(None, _context()) is True
    assert guard.deny_reason(None, _context()) is None


def test_night_reason_wins_over_echo() -> None:
    """Настоящая причина важнее эха: «спим» называется своим именем."""
    guard = _guard()

    assert guard(None, _context(sleep_modifier_on=True, light_off_at=NOW - 1.0)) is False
    assert guard.deny_reason(None, _context(sleep_modifier_on=True, light_off_at=NOW - 1.0)) == (
        "sleep_modifier"
    )


def test_daylight_reason_wins_over_echo() -> None:
    """Светло — тоже настоящая причина, и она важнее эха."""
    guard = _guard()

    assert guard.deny_reason(None, _context(daylight=True, light_off_at=NOW - 1.0)) == "daylight"


def test_window_boundary_is_inclusive() -> None:
    """Граница окна включительна: ровно на границе движение ещё эхо."""
    guard = _guard()

    assert guard(None, _context(light_off_at=NOW - DEFAULT_MOTION_ECHO_SEC)) is False
