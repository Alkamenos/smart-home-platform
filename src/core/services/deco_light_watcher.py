"""Сверка вечернего света с темнотой: страховка от потерянного события.

Событие заката приходит один раз в сутки, и оно легко теряется: платформа
перезапустилась вечером, соединение с Home Assistant отвалилось в момент
перехода через горизонт, рестарт контейнера пришёлся на вечер. Всё это
проверено в бою 2026-10-09: закат в 18:32 прошёл, пока вечернего поведения в
манифесте ещё не было, и ночное освещение не загорелось — ждать следующего
заката было бы сутки.

Сверка спрашивает не «было ли событие», а «темно ли сейчас и горит ли нужный
свет»: пока темно и свет выключен — событие доставляется снова. Повтор
безопасен: после включения автомат переходит в `ON_DECO`, а повторный закат
ведёт в `ON_DECO → ON_DECO` без действия.

Вторая половина — **обратная**: на рассвете свет гаснет, даже если событие
тоже потерялось.

Интервал — 15 минут. За это время «темно, а свет не горит» успевает
привлечь внимание, и платформа не делает работу вхолостую: пока состояние
совпадает с решением, ничего не отправляется.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from core.fsm.engine import FSMEngine


class DecorativeLightWatcher:
    """Следить, чтобы вечерний свет горел в темноте и не горел на рассвете.

    Args:
        engine: Движок автоматов.
        daylight_supplier: Источник признака «светло ли сейчас». Значение
            `None` означает «неизвестно» — тогда сверка молчит, потому что
            действовать по неизвестному признаку означает угадывать.
        interval_minutes: Как часто сверять. По умолчанию 15 минут: за это время
            пропавший свет заметен, а работы сверка не создаёт, пока состояние
            совпадает с решением.
    """

    def __init__(
        self,
        engine: FSMEngine,
        daylight_supplier: Any,
        interval_minutes: float = 15.0,
    ) -> None:
        self.engine = engine
        self._daylight = daylight_supplier
        self.interval_minutes = interval_minutes
        self._task: asyncio.Task[None] | None = None

    async def check_once(self) -> None:
        """Сверить состояние вечернего света с темнотой и исправить расхождение.

        Returns:
            Ничего.
        """
        daylight = self._daylight() if callable(self._daylight) else self._daylight
        if daylight is None:
            # Признак неизвестен (состояние солнца ещё не прочитано): гасить
            # нельзя — это выключило бы свет среди ночи из-за молчания датчика.
            logger.debug("Сверка вечернего света пропущена: состояние солнца неизвестно")
            return

        event = "sunset_started" if not daylight else "sunrise_started"

        # Сверяется только расхождение, а не сам факт темноты: пока темно и свет
        # горит (или светло и не горит), доставлять событие незачем — в журнале
        # это были бы пустые переходы каждые 15 минут, то есть шум, который
        # утренний разбор только засорит.
        stale = [
            entity_id
            for entity_id in self.engine.entities_with_trigger(event)
            if self._out_of_sync(entity_id, want_light=not daylight)
        ]
        if not stale:
            return

        logger.warning(f"Вечерний свет не соответствует времени суток ({event}): исправляю {stale}")
        for entity_id in stale:
            try:
                await self.engine.trigger(entity_id, event, respect_debounce=False)
            except Exception:  # noqa: BLE001 — одно устройство не мешает остальным
                logger.warning(f"Сверка вечернего света: {entity_id} не обработал {event}")

    def _out_of_sync(self, entity_id: str, *, want_light: bool) -> bool:
        """Расходится ли состояние автомата с тем, что должно быть.

        Состояние автомата — то, что платформа считает включённым, и оно может
        разойтись с reality в обе стороны. Первое — событие потерялось (свет
        нужен, а автомат выключен), и это вчерашний случай с пропущенным
        закатом. Второе — событие пришло, а команда не ушла (свет выключен, а
        автомат считает включённым): повтор события опустит автомат и выключит
        свет по-настоящему.

        Args:
            entity_id: Автомат.
            want_light: Должен ли свет гореть сейчас.

        Returns:
            True, если состояние не совпадает с ожидаемым.
        """
        state = self.engine.get_state(entity_id)
        if state is None:
            # Автомата нет: доставлять некому, но и «всё в порядке» нельзя —
            # журнал покажет расхождение, а не промолчит.
            return True
        is_on = state.current_state.upper().startswith("ON")
        return is_on != want_light

    async def _run(self) -> None:
        """Сверять состояние до остановки.

        Первый проход идёт раньше обычного интервала: сверка стартует вместе с
        платформой, а состояние солнца читается позже, при подключении к Home
        Assistant. Без раннего прохода первый настоящий закат после старта
        ждал бы полный интервал, а при старте вечером — и вовсе остался бы без
        сверки до следующего раза.

        Returns:
            Ничего.
        """
        interval = max(self.interval_minutes, 1.0) * 60.0
        delay = min(60.0, interval)
        while True:
            await asyncio.sleep(delay)
            delay = interval
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — фоновая сверка не должна умирать
                logger.warning(f"Сверка вечернего света не удалась: {exc}")

    def start(self) -> None:
        """Запустить сверку в фоне.

        Returns:
            Ничего.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(f"Сверка вечернего света: каждые {self.interval_minutes:g} мин")

    async def stop(self) -> None:
        """Остановить сверку.

        Returns:
            Ничего.
        """
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — остановка не шумит
                return

    def describe(self) -> dict[str, Any]:
        """Описание сверки для журнала и готовности.

        Returns:
            Словарь с интервалом и состоянием признака «светло».
        """
        daylight = self._daylight() if callable(self._daylight) else self._daylight
        return {
            "interval_minutes": self.interval_minutes,
            "daylight": daylight,
            "running": self._task is not None and not self._task.done(),
        }
