"""Суточный цикл платформы: гасит свет по часам и поднимает дом утром.

Задача — чтобы «не горит всю ночь» обеспечивалось часами, а не датчиками: в доме
четыре комнаты без датчиков движения, там автоматика по движению не работает, и
единственный способ погасить свет — по расписанию.

Сервис нарочно узкий: он знает время и умеет отправить событие тем автоматам,
где переход на него есть. Он не решает, что именно должно происходить в ответ —
это дело описаний поведения.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from core.fsm.engine import FSMEngine
from core.scheduling.daily import DailyClock


async def deliver_to_automata(
    engine: FSMEngine,
    event: str,
    source: str = "Суточный цикл",
) -> None:
    """Отправить событие всем автоматам, которые на него реагируют.

    Общая доставка для событий, которые приходят не от датчика: будильник
    суток (``quiet_hours_started``, ``day_started``) и переключение
    модификатора «мы спим» (``sleep_started``). Событие получает только тот
    автомат, у которого на него есть переход, — остальные не шумят.

    Args:
        engine: Движок автоматов.
        event: Имя события, например ``sleep_started``.
        source: Подпись отказов в журнале; по ней утром видно, откуда событие.

    Returns:
        Ничего.
    """
    for entity_id in engine.entities_with_trigger(event):
        try:
            # Дебаунс не применяется: событие не дребезг датчика, а
            # отбрасывание означало бы «свет не погас вовремя».
            await engine.trigger(entity_id, event, respect_debounce=False)
        except Exception:  # noqa: BLE001 — одно устройство не роняет остальные
            # Ошибка одного автомата не должна останавливать доставку: иначе
            # сломанный светильник отменяет выключение всего дома.
            logger.warning(f"{source}: {entity_id} не обработал {event}")


class DayCycleService:
    """Расписание суток, отправленное автоматам.

    Args:
        clock: Часы суточных событий.
        engine: Движок автоматов.
    """

    def __init__(self, clock: DailyClock, engine: FSMEngine) -> None:
        self.clock = clock
        self.engine = engine
        self._task: asyncio.Task[None] | None = None

    async def handle(self, event: str) -> None:
        """Отправить событие всем автоматам, которые на него реагируют.

        Args:
            event: Имя события, например ``quiet_hours_started``.

        Returns:
            Ничего.
        """
        await deliver_to_automata(self.engine, event)

    def start(self) -> None:
        """Запустить цикл в фоне.

        Returns:
            Ничего.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.clock.run(self.handle))

    async def stop(self) -> None:
        """Остановить цикл.

        Returns:
            Ничего.
        """
        self.clock.stop()
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001 — остановка не должна шуметь
                return

    def describe(self) -> dict[str, Any]:
        """Описание расписания для журнала и готовности.

        Returns:
            Словарь «событие → час по-домашнему».
        """
        return {name: when.strftime("%H:%M") for when, name in self.clock.events.items()}
