"""Суточные события платформы: «пора погасить» и «наступил день».

Задача — чтобы свет гас сам в заданный час, а не ждал, пока кто-то пошевелится:
в доме четыре комнаты без датчиков движения, там автоматика не работает вовсе, и
единственный способ не оставить свет гореть всю ночь — выключать по часам.

Расписание суточное, а не «через N секунд»: момент вычисляется каждый раз заново
от текущего времени в часах дома, поэтому перезапуск контейнера не сдвигает
расписание, а перевод часов и переход на летнее время не оставляют событие
назавтра. Часовой пояс берётся тот же, что и у правил света: контейнер живёт в
UTC, дом — в своём поясе, и «23:00» здесь — это 23:00 дома.

Время в этой задаче подставляется снаружи: проверки не ждут реальных часов.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import datetime as dt
from collections.abc import Callable
from typing import Any
from zoneinfo import ZoneInfo


#: Часовой пояс дома по умолчанию для проверок: UTC+5 без летнего времени.
HOUSE = ZoneInfo("Asia/Yekaterinburg")

#: Шаг ожидания до пересчёта расписания.
TICK_SEC = 20.0


class DailyClock:
    """Суточные события по часам дома.

    Args:
        events: События в виде «час:минута → имя события». Одному часу могут
            отвечать несколько событий, а одно событие может наступать в разное
            время суток (например, вечернее включение и утреннее выключение).
        timezone: Часовой пояс дома.
        now: Источник времени; подменяется в проверках.
        sleep: Ожидание; подменяется в проверках.
    """

    def __init__(
        self,
        events: dict[dt.time, str],
        *,
        timezone: ZoneInfo = HOUSE,
        now: Callable[[], dt.datetime] | None = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
    ) -> None:
        self.events = dict(events)
        self.timezone = timezone
        self._now = now or (lambda: dt.datetime.now(timezone))
        self._sleep = sleep
        self.fired: list[tuple[dt.datetime, str]] = []
        self._stopped = False

    def next_occurrence(self, moment: dt.datetime) -> tuple[dt.datetime, str] | None:
        """Ближайшее наступление любого события после указанного момента.

        Args:
            moment: Момент, от которого ищется наступление.

        Returns:
            Пара «момент наступления — имя события» либо None, если событий нет.
        """
        if not self.events:
            return None
        candidates: list[tuple[dt.datetime, str]] = []
        for when, name in self.events.items():
            same_day = moment.replace(hour=when.hour, minute=when.minute, second=0, microsecond=0)
            if same_day <= moment:
                same_day = same_day + dt.timedelta(days=1)
            candidates.append((same_day, name))
        return min(candidates, key=lambda pair: pair[0])

    def due(self, moment: dt.datetime) -> list[tuple[dt.datetime, str]]:
        """События, наступившие за прошедший промежуток.

        Args:
            moment: Момент, для которого проверяется наступление.

        Returns:
            Список пар «момент — имя события», которые наступили с прошлой
            проверки включительно.
        """
        if not self.events or not self.fired:
            return self._not_fired(moment, moment)
        last = self.fired[-1][0]
        return self._not_fired(last, moment)

    def _not_fired(self, since: dt.datetime, until: dt.datetime) -> list[tuple[dt.datetime, str]]:
        """Собрать наступления событий в промежутке.

        Args:
            since: Начало промежутка.
            until: Конец промежутка.

        Returns:
            События, наступившие в промежутке, по порядку.
        """
        due: list[tuple[dt.datetime, str]] = []
        # Вчерашний день тоже просматривается: событие, наступившее, пока
        # контейнер стоял, должно наступить при пробуждении, а не ждать следующих
        # суток. Без этого перезапуск среди ночи молча пропускал бы «погасить
        # свет» — то есть ровно то, ради чего механизм написан.
        for offset in (-1, 0, 1):
            day = (until + dt.timedelta(days=offset)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            for when, name in self.events.items():
                moment = day + dt.timedelta(hours=when.hour, minutes=when.minute)
                if since < moment <= until:
                    due.append((moment, name))
        return sorted(due)

    def fire(self, moment: dt.datetime, name: str) -> None:
        """Отметить событие как наступившее.

        Args:
            moment: Момент наступления.
            name: Имя события.
        """
        self.fired.append((moment, name))

    async def run(self, on_event: Callable[[str], Any]) -> None:
        """Работать, пока не остановят, вызывая обработчик в назначенный час.

        Args:
            on_event: Обработчик события по его имени.

        Returns:
            Ничего. Задача живёт до отмены.
        """
        self._stopped = False
        while not self._stopped:
            now = self._now()
            for moment, name in self.due(now):
                self.fire(moment, name)
                result = on_event(name)
                if asyncio.iscoroutine(result):
                    await result
            await self._sleep(TICK_SEC)

    def stop(self) -> None:
        """Остановить цикл событий.

        Returns:
            Ничего.
        """
        self._stopped = True
