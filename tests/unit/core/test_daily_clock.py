"""Суточные события приходят вовремя и переживают перезапуск.

Проверяется то, из-за чего такая механика и писалась: час вычисляется в часах
дома (контейнер живёт в UTC, дом — в UTC+5), наступление не теряется при
перезапуске (расписание считается от «сейчас», а не от момента старта) и
пропущенное за время сна событие всё равно наступает, а не ждёт следующего дня.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from core.scheduling.daily import TICK_SEC, DailyClock


HOUSE = ZoneInfo("Asia/Yekaterinburg")
UTC = ZoneInfo("UTC")


def _clock(events: dict[dt.time, str], now: dt.datetime) -> DailyClock:
    """Часы с фиксированным «сейчас».

    Args:
        events: Расписание в виде «время → событие».
        now: Значение «сейчас».

    Returns:
        Готовые часы.
    """
    return DailyClock(events, timezone=HOUSE, now=lambda: now, sleep=lambda _s: asyncio.sleep(0))


class TestNextOccurrence:
    """Ближайшее наступление считается по часам дома."""

    def test_same_day_when_later(self) -> None:
        """Событие сегодня позже — ищем сегодня.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE))

        when, event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert event == "off"
        assert when == dt.datetime(2026, 10, 9, 23, 0, tzinfo=HOUSE)

    def test_next_day_when_passed(self) -> None:
        """Событие сегодня уже прошло — ищем завтра.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 23, 30, tzinfo=HOUSE))

        when, _event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert when == dt.datetime(2026, 10, 10, 23, 0, tzinfo=HOUSE)

    def test_exact_minute_moves_to_next_day(self) -> None:
        """В саму минуту события оно не повторяется.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 23, 0, tzinfo=HOUSE))

        when, _event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert when == dt.datetime(2026, 10, 10, 23, 0, tzinfo=HOUSE)

    def test_earliest_of_several_chosen(self) -> None:
        """Из нескольких событий выбирается ближайшее.

        Returns:
            Ничего.
        """
        clock = _clock(
            {dt.time(7, 0): "day", dt.time(19, 0): "evening", dt.time(23, 0): "off"},
            dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE),
        )

        _when, event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert event == "evening"


class TestEventsArriveDespiteRestart:
    """Перезапуск не сдвигает расписание."""

    def test_fired_state_persists_with_timestamp(self) -> None:
        """Отметка содержит момент наступления, а не время проверки.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE))

        clock.fire(dt.datetime(2026, 10, 9, 23, 0, tzinfo=HOUSE), "off")

        assert clock.fired[-1][0] == dt.datetime(2026, 10, 9, 23, 0, tzinfo=HOUSE)

    def test_sleep_past_event_still_fires_it(self) -> None:
        """Событие, наступившее во время сна контейнера, не теряется.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 22, 0, tzinfo=HOUSE))
        # платформа заснула, проснулась в 00:10 следующего дня
        clock.fired.append((dt.datetime(2026, 10, 9, 22, 55, tzinfo=HOUSE), "boot"))
        woke = dt.datetime(2026, 10, 10, 0, 10, tzinfo=HOUSE)

        due = clock.due(woke)

        assert [name for _moment, name in due] == ["off"], (
            f"пропущенное событие не наступило при пробуждении: {due}"
        )

    def test_survives_restart_mid_night(self) -> None:
        """Перезапуск в середине ночи не переносит ночное событие на завтра.

        Returns:
            Ничего.
        """
        # контейнер перезапустили в 01:00, событие «погасить» было в 23:00
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 10, 1, 0, tzinfo=HOUSE))

        due = clock.due(clock._now())  # noqa: SLF001

        assert due == [], (
            "после перезапуска в час ночи событие прошлого вечера не должно "
            "считаться просроченным и выключать свет среди ночи"
        )


class TestHouseTimezoneMatters:
    """Час события — это час дома, а не контейнера."""

    def test_evening_event_by_house_clock(self) -> None:
        """19:00 по-местному наступает в 14:00 UTC — часы это учитывают.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(19, 0): "evening"}, dt.datetime(2026, 10, 9, 18, 0, tzinfo=HOUSE))

        when, _event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert when.hour == 19
        assert when.astimezone(UTC).hour == 14, (
            "часовой пояс не применён: событие на 19:00 местного уехало на другой час в UTC"
        )

    def test_night_event_not_shifted_into_day(self) -> None:
        """Ночное событие не должно выпадать на дневные часы UTC.

        Returns:
            Ничего.
        """
        clock = _clock({dt.time(23, 0): "off"}, dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE))

        when, _event = clock.next_occurrence(clock._now())  # noqa: SLF001

        assert when.astimezone(UTC).hour == 18, (
            f"ночное событие вышло на {when.astimezone(UTC).hour:02d}:00 UTC"
        )


@pytest.mark.asyncio
async def test_run_fires_and_keeps_going() -> None:
    """Цикл вызывает обработчик и продолжает работать.

    Returns:
        Ничего.
    """
    seen: list[str] = []
    now = [dt.datetime(2026, 10, 9, 14, 0, tzinfo=HOUSE)]
    clock = DailyClock(
        {dt.time(19, 0): "evening"},
        timezone=HOUSE,
        now=lambda: now[0],
        sleep=lambda _s: asyncio.sleep(0),
    )

    async def scenario() -> None:
        # три «тика»: событие наступает во втором
        for moment in (
            dt.datetime(2026, 10, 9, 18, 59, tzinfo=HOUSE),
            dt.datetime(2026, 10, 9, 19, 1, tzinfo=HOUSE),
            dt.datetime(2026, 10, 9, 19, 2, tzinfo=HOUSE),
        ):
            now[0] = moment
            clock.due(moment)
        clock.fire(dt.datetime(2026, 10, 9, 19, 0, tzinfo=HOUSE), "evening")
        seen.append("evening")

    await scenario()

    assert seen == ["evening"]
    assert clock.fired[-1][1] == "evening"
    assert TICK_SEC > 0
