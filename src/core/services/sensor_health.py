"""Слежение за зарядом батарей датчиков.

Датчики на батарейках молчат, когда батарейка села, и до этого момента у
платформы нет никакого признака: датчик просто не присылает показаний. В доме
2026-10-10 датчик террасы показывал заряд 1 %, а о проблеме узнали по тому,
что датчик отключился, — то есть потеряв его.

Наблюдение узкое и намеренно такое: только батарейки тех датчиков, по которым
принимаются решения климата. Сквозная проверка здоровья всего дома — отдельная
фича (`BACKLOG.md`, F6); она построит на этом наблюдении.

Правило о молчании повторяет принятое в движке для отказов: проблема
сообщается один раз, пока она не изменилась. Иначе датчик на 1 % писал бы
предупреждение каждые 15 минут, и список проблем перестал бы быть списком.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger


#: Заряд ниже этого процента считается требующим замены. Ниже — уже пора, выше —
#: успеет сесть по дороге. Значение выбрано по датчикам дома: в 2026-10-10
#: терраса стояла на 1 %, спальня и санузел — на 81 и 86 %.
DEFAULT_LOW_THRESHOLD = 20.0

#: Как часто проверяется заряд. Раз в сутки достаточно: батарейка не садится
#: за час, а список проблем не должен обновляться чаще, чем он меняется.
DEFAULT_INTERVAL_MINUTES = 360.0


def _as_percent(state: str | None) -> float | None:
    """Заряд из состояния Home Assistant как число.

    Args:
        state: Состояние сущности.

    Returns:
        Процент либо ``None``, если значение непригодно.
    """
    if state is None:
        return None
    text = state.strip()
    if not text or text in ("unavailable", "unknown"):
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    # Заряд не может быть отрицательным или выше сотни: такие значения означают,
    # что датчик отдаёт мусор, и тревожиться по ним незачем.
    if not 0.0 <= value <= 100.0:
        return None
    return value


class SensorHealthService:
    """Следить за зарядом батарей датчиков, на решения которых опирается климат.

    Args:
        adapter: Адаптер Home Assistant с методом
            ``get_entity_state(entity_id)``.
        battery_entities: Сущности заряда, которые нужно проверять.
        low_threshold: Процент, ниже которого батарейка считается севшей.
        interval_minutes: Как часто проверять.
    """

    def __init__(
        self,
        adapter: Any,
        battery_entities: list[str],
        low_threshold: float = DEFAULT_LOW_THRESHOLD,
        interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
    ) -> None:
        self._adapter = adapter
        self._batteries = list(battery_entities)
        self._low_threshold = low_threshold
        self._interval_minutes = interval_minutes
        self._task: asyncio.Task[None] | None = None
        self._checked = 0
        self._read: dict[str, float | None] = {}
        self._reported: set[str] = set()

    async def check_once(self) -> list[str]:
        """Проверить заряд один раз.

        Returns:
            Сущности с зарядом ниже порога. Батарейка, о которой уже сообщали и
            у которой заряд не изменился, повторно не возвращается: список
            проблем нужен для разбора, а не для подтверждения, что всё так же.
        """
        low_now: list[str] = []
        self._checked = 0

        for entity in self._batteries:
            state = await self._adapter.get_entity_state(entity)
            percent = _as_percent(state)
            self._checked += 1
            self._read[entity] = percent

            if percent is None:
                # Неизвестно — не значит «ноль». Молчащий датчик и севшая
                # батарейка выглядели бы в списке проблем одинаково, и чинить
                # пришлось бы то, чего нет.
                continue
            if percent < self._low_threshold:
                low_now.append(entity)

        for entity in set(low_now) - self._reported:
            logger.warning(
                f"Батарейка датчика {entity} на {self._read[entity]:.0f} % — "
                f"порог {self._low_threshold:.0f} %. Датчик замолчит раньше, чем "
                "платформа заметит: обогрев в этой комнате остановится."
            )
        self._reported = set(low_now)
        return low_now

    def describe(self) -> dict[str, Any]:
        """Состояние наблюдения для сводки готовности.

        Returns:
            Словарь с порогом, прочитанными значениями и списком проблем.
        """
        return {
            "low_threshold": self._low_threshold,
            "interval_minutes": self._interval_minutes,
            "checked": self._checked,
            "batteries": dict(self._read),
            "low_batteries": sorted(self._reported),
            "running": self._task is not None and not self._task.done(),
        }

    async def _run(self) -> None:
        """Проверять заряд с заданным интервалом до остановки.

        Первая проверка идёт сразу, а не через интервал: о севшей батарейке
        полезно узнать при старте платформы, ведь до следующего суточного прохода
        датчик может замолчать — и тогда предупреждение уже не поможет.

        Returns:
            Ничего.
        """
        interval = max(self._interval_minutes, 1.0) * 60.0
        delay = min(60.0, interval)
        while True:
            await asyncio.sleep(delay)
            delay = interval
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — фоновая проверка не должна умирать
                logger.warning(f"Проверка батареек не удалась: {exc}")

    def start(self) -> None:
        """Запустить наблюдение в фоне.

        Returns:
            Ничего.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(
                f"Наблюдение за батарейками: {len(self._batteries)} датчиков, "
                f"порог {self._low_threshold:.0f} %"
            )

    async def stop(self) -> None:
        """Остановить наблюдение.

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
