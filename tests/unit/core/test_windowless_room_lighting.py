"""Свет в комнатах без окон: санузел и контейнер.

Боевой дефект 2026-10-10 (контейнер, свежий запуск): датчик движения в санузле
и контейнере срабатывал штатно, а свет не включался. Журнал:

    Routing: sensor=binary_sensor.vykliuchatel_sanuzel_presence
        -> fsm=light.vykliuchatel_sanuzel_switch1_lighting_10, event=motion_detected
    FSMEngine: отказ по сущности ... (daylight)

Причина в `_dark_enough`: пока солнце над горизонтом, условие `may_turn_on`
отказывает ВСЕМ комнатам без разбора - днём включать свет бессмысленно. Для
гостиной это верно, но в санузле и контейнере окон нет: там темно круглосуточно,
и единственный свет - электрический. Владелец сформулировал требование прямо:
санузел включается по движению днём, контейнер - вообще всегда.

Правило, которое проверяет этот файл: комната из `always_on_motion_rooms`
включается по движению в любое время суток. Модификатор «мы спим» при этом
остаётся выше всего: спящим яркий свет не нужен ни в одной комнате, включая
санузел (требование владельца 2026-10-09).

Здесь же проверка, что список не превращается в «разрешено всем» и что
остальные комнаты по-прежнему не включают свет среди дня.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from core.guards.builtin import make_may_turn_on


#: Часовой пояс дома: UTC+5 без перехода на летнее время.
HOUSE = ZoneInfo("Asia/Yekaterinburg")

#: Комната без окон: свет нужен всегда.
WINDOWLESS = "sanuzel"

#: Обычная комната с окнами: днём свет не нужен.
DAY_ROOM = "gostinaia"


def _at(moment: datetime) -> Any:
    """Условие «можно ли включать» с часами, зафиксированными на момент

    Args:
        moment: Момент, который для условия является «сейчас».

    Returns:
        Функция условия
    """
    return make_may_turn_on(now=lambda _tz: moment)


def _ctx(room: str, **params: Any) -> dict[str, Any]:
    """Контекст перехода для комнаты.

    Args:
        room: Идентификатор комнаты.
        **params: Параметры поведения.

    Returns:
        Контекст для условия
    """
    return {"room": room, **params}


class TestDaylightDeny:
    """Днём в комнате с окнами свет по движению не включается."""

    def test_windowed_room_denied_in_daylight(self) -> None:
        """Солнце над горизонтом — свет в гостиной не включаем."""
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=True)) is False, (
            "в комнате с окнами днём свет не нужен: солнце над горизонтом"
        )

    def test_deny_reason_names_daylight(self) -> None:
        """Отказ называется «светло», а не «нечем объяснить»."""
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert guard.deny_reason(None, _ctx(DAY_ROOM, daylight=True)) == "daylight"


class TestWindowlessRooms:
    """В комнатах без окон движение включает свет всегда."""

    def test_windowless_room_allowed_in_daylight(self) -> None:
        """Санузел включается по движению средь бела дня.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert (
            guard(None, _ctx(WINDOWLESS, daylight=True, always_on_motion_rooms=[WINDOWLESS]))
            is True
        ), (
            "в санузле окон нет: солнце над горизонтом не делает комнату светлой, "
            "а движение обязано включать свет (требование владельца 2026-10-10)"
        )

    def test_windowless_room_allowed_at_night(self) -> None:
        """Ночью в санузле свет включается и без нового правила.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 23, 30, tzinfo=HOUSE))

        assert (
            guard(
                None,
                _ctx(
                    WINDOWLESS,
                    daylight=False,
                    always_on_motion_rooms=[WINDOWLESS],
                    night_motion_rooms=[WINDOWLESS],
                ),
            )
            is True
        )

    def test_container_light_allowed_in_daylight(self) -> None:
        """Контейнер включается по движению днём — окон нет и там.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 14, 0, tzinfo=HOUSE))

        assert guard(None, _ctx("konteiner", daylight=True, always_on_motion_rooms=["konteiner"]))

    def test_list_does_not_allow_other_rooms(self) -> None:
        """Список не превращается в «разрешено всем».

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(DAY_ROOM, daylight=True, always_on_motion_rooms=[WINDOWLESS])) is (
            False
        ), "гостиная не в списке: солнце над горизонтом, свет не нужен"

    def test_without_list_behaviour_unchanged(self) -> None:
        """Без нового параметра поведение прежнее — свет днём не включается.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert guard(None, _ctx(WINDOWLESS, daylight=True)) is False


class TestSleepBeatsAlwaysOn:
    """Модификатор «мы спим» остаётся выше нового правила."""

    def test_sleep_modifier_denies_windowless_room(self) -> None:
        """Спящим яркий свет не нужен даже в санузле.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 23, 30, tzinfo=HOUSE))

        assert (
            guard(
                None,
                _ctx(
                    WINDOWLESS,
                    daylight=False,
                    always_on_motion_rooms=[WINDOWLESS],
                    sleep_modifier_on=True,
                ),
            )
            is False
        ), (
            "пока включён «мы спим», яркий свет не включается ни в одной комнате — "
            "иначе санузел светит в полную яркость ночью"
        )

    def test_sleep_modifier_denies_in_daylight(self) -> None:
        """Днём при включённом «мы спим» санузел тоже не загорается.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert (
            guard(
                None,
                _ctx(
                    WINDOWLESS,
                    daylight=True,
                    always_on_motion_rooms=[WINDOWLESS],
                    sleep_modifier_on=True,
                ),
            )
            is False
        )

    def test_sleep_off_allows_windowless_room(self) -> None:
        """Выключенный «мы спим» возвращает санузлу обычное правило.

        Returns:
            Ничего.
        """
        guard = _at(datetime(2026, 10, 10, 12, 0, tzinfo=HOUSE))

        assert (
            guard(
                None,
                _ctx(
                    WINDOWLESS,
                    daylight=True,
                    always_on_motion_rooms=[WINDOWLESS],
                    sleep_modifier_on=False,
                ),
            )
            is True
        )
