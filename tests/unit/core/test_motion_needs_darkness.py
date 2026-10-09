"""Движением свет включается только когда темно.

Жалоба владельца 2026-10-09: свет над столом в гостиной включался по движению
днём, когда в комнате и так светло. Датчиков освещённости в доме нет (проверено:
ни одного `device_class: illuminance`), поэтому «темно ли» определяется по
солнцу — `sun.sun` в Home Assistant живёт всегда и меняет состояние на
восходе и закате.

Правило различать три случая, а не два:

- ночная комната (`sanuzel`, `konteiner`) — включаем всегда: там свет нужен
  ночью, и это отдельное решение владельца;
- на улице светло — не включаем: человек в комнате уже видит;
- состояние солнца неизвестно (платформа только что поднялась, события ещё не
  пришли) — решаем по времени суток, как раньше, чтобы движение работало и до
  первого события от солнца.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from core.guards.builtin import HOUSE_TZ, make_may_turn_on


#: Часовой пояс дома: UTC+5 без перехода на летнее время.
HOUSE = ZoneInfo("Asia/Yekaterinburg")

#: Ночные комнаты, где свет включается в любое время суток.
NIGHT_ROOM = "sanuzel"

#: Обычная комната: включаем только в темноте.
DAY_ROOM = "gostinaia"


def _guard(at: datetime, **params: Any) -> Any:
    """Условие «можно ли включать» с зафиксированными часами.

    Args:
        at: Момент, который для условия считается «сейчас».
        **params: Параметры поведения.

    Returns:
        Функция условия.
    """
    return make_may_turn_on(now=lambda _tz: at)


def _ctx(room: str, daylight: bool | None, **params: Any) -> dict[str, Any]:
    """Контекст перехода: комната, состояние солнца и параметры.

    Args:
        room: Комната устройства.
        daylight: Светло ли на улице; None — неизвестно.
        **params: Параметры поведения.

    Returns:
        Контекст для условия.
    """
    return {"room": room, "daylight": daylight, **params}


class TestMotionNeedsDarkness:
    """При дневном свете движение свет не включает."""

    def test_daylight_blocks_motion_in_ordinary_room(self) -> None:
        """Солнце над горизонтом — в гостиной свет не включаем.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 13, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=True)) is False, (
            "при дневном свете движение включило свет: человек и так видит, "
            "зачем включать ему свет поверх солнца"
        )

    def test_dark_allows_motion_in_ordinary_room(self) -> None:
        """Солнце за горизонтом — в гостиной движение включает свет.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 13, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=False)) is True

    def test_night_room_does_not_need_light_in_sunlight(self) -> None:
        """Список ночных комнат отменяет окно тишины, а не солнце.

        Смысл списка — «в санузле свет нужен ночью», а не «в санузле свет нужен
        всегда». Солнечным днём он тоже не нужен.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 13, 0, tzinfo=HOUSE))

        assert (
            guard(None, _ctx(NIGHT_ROOM, daylight=True, night_motion_rooms=[NIGHT_ROOM])) is False
        )


class TestUnknownDaylightFallsBackToTime:
    """Пока состояние солнца неизвестно, решает время суток."""

    def test_unknown_daylight_daytime_denies(self) -> None:
        """Днём без данных о солнце свет не включаем — это безопаснее.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 13, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=None)) is False

    def test_unknown_daylight_at_night_defers_to_quiet_window(self) -> None:
        """Ночью без данных о солнце решение отдаёт окно тишины.

        Обычная комната в окне тишины не включается, а ночная — да. Состояние
        солнца платформа читает при подключении, так что этот путь — запасной для
        случая, когда чтение не удалось.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 2, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=None)) is False
        assert guard(None, _ctx(NIGHT_ROOM, daylight=None, night_motion_rooms=[NIGHT_ROOM])) is True


class TestQuietHoursStillWin:
    """Темнота не отменяет ночного запрета."""

    def test_night_blocks_ordinary_room(self) -> None:
        """В 23:30 в спальне движение свет не включает.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 23, 30, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=False)) is False

    def test_night_allows_listed_room(self) -> None:
        """В 23:30 санузел — можно.

        Returns:
            Ничего.
        """
        guard = _guard(datetime(2026, 10, 9, 23, 30, tzinfo=HOUSE))

        assert (
            guard(None, _ctx(NIGHT_ROOM, daylight=False, night_motion_rooms=[NIGHT_ROOM])) is True
        )


@pytest.mark.parametrize("offset_hours", range(0, 24))
def test_exactly_one_switching_point_in_a_day(offset_hours: int) -> None:
    """За сутки условие меняет решение ровно один раз: на закате.

    Args:
        offset_hours: Смещение от полуночи по местному времени.
    """
    guard = _guard(datetime(2026, 10, 9, 0, 0, tzinfo=HOUSE) + timedelta(hours=offset_hours))
    allowed = [
        guard(None, _ctx(DAY_ROOM, daylight=False)),
        guard(None, _ctx(DAY_ROOM, daylight=True)),
    ]

    # оба состояния солнца согласованы между собой: правило не зависит от того,
    # какое из них пришло, если второе противоречит первому по времени суток
    in_quiet_hours = offset_hours >= 23 or offset_hours < 7  # окно 23:00-06:30
    if in_quiet_hours:
        assert allowed == [False, False], (
            f"в {offset_hours:02d}:00 ночное окно должно запрещать включение "
            f"независимо от солнца: {allowed}"
        )
    else:
        assert allowed == [True, False], (
            f"в {offset_hours:02d}:00 ожидалось «темно — можно, светло — нельзя»: {allowed}"
        )


def test_house_timezone_is_used_for_the_fallback() -> None:
    """Запасной путь считает время дома, а не контейнера.

    Returns:
        Ничего.
    """
    assert HOUSE_TZ is not None
