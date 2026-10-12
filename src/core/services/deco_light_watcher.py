"""Сверка вечернего света с временем суток и отбоем: страховка от потери события.

Событие заката приходит один раз в сутки, и оно легко теряется: платформа
перезапустилась вечером, соединение с Home Assistant отвалилось в момент
перехода через горизонт, рестарт контейнера пришёлся на вечер. Всё это
проверено в бою 2026-10-09: закат в 18:32 прошёл, пока вечернего поведения в
манифесте ещё не было, и ночное освещение не загорелось — ждать следующего
заката было бы сутки.

Сверка спрашивает не «было ли событие», а «совпадает ли свет с решением»:
темно и свет должен гореть, а его нет — событие доставляется снова. Повтор
безопасен: после включения автомат переходит в `ON_DECO`, а повторный закат
ведёт в `ON_DECO → ON_DECO` без действия.

Вторая половина — **обратная**: на рассвете свет гаснет, даже если событие
тоже потерялось.

Третья — **отбой**. Свет, гаснущий по «мы спим» (`off_by: sleep`, гирлянда), в
темноте при включённом модификаторе должен быть ВЫКЛЮЧЕН. Раньше сверка этого
не знала: увидев «темно, а света нет» через минуту после отбоя, она включала
гирлянду обратно — боевой дефект, вскрытый владельцем ночью 2026-10-13. Теперь
отбой учитывается: такой свет не возвращают, а если он всё же горит при отбое,
сверка шлёт `sleep_started` и гасит его.

Интервал — 15 минут. За это время расхождение успевает привлечь внимание, а
платформа не делает работу вхолостую: пока состояние совпадает с решением,
ничего не отправляется.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from core.fsm.engine import FSMEngine


class DecorativeLightWatcher:
    """Следить, чтобы вечерний свет совпадал с временем суток и отбоем.

    Args:
        engine: Движок автоматов.
        daylight_supplier: Источник признака «светло ли сейчас». Значение
            `None` означает «неизвестно» — тогда сверка молчит, потому что
            действовать по неизвестному признаку означает угадывать.
        interval_minutes: Как часто сверять. По умолчанию 15 минут: за это
            время пропавший свет заметен, а работы сверка не создаёт, пока
            состояние совпадает с решением.
        sleeping_supplier: Источник признака «мы спим». Нужен, чтобы свет,
            гаснущий по отбою (`off_by: sleep`), не включался обратно, пока дом
            спит (боевой дефект 2026-10-13). `None` — «не спим».
    """

    def __init__(
        self,
        engine: FSMEngine,
        daylight_supplier: Any,
        interval_minutes: float = 15.0,
        sleeping_supplier: Any = None,
    ) -> None:
        self.engine = engine
        self._daylight = daylight_supplier
        self._sleeping_supplier = sleeping_supplier
        self.interval_minutes = interval_minutes
        self._task: asyncio.Task[None] | None = None

    async def check_once(self) -> None:
        """Сверить вечерний свет с временем суток и отбоем.

        Returns:
            Ничего.
        """
        daylight = self._daylight() if callable(self._daylight) else self._daylight
        if daylight is None:
            # Признак неизвестен (состояние солнца ещё не прочитано): гасить
            # нельзя — это выключило бы свет среди ночи из-за молчания датчика.
            logger.debug("Сверка вечернего света пропущена: состояние солнца неизвестно")
            return

        sleeping = self._sleeping()
        for entity_id in self.engine.entities_with_trigger("sunset_started"):
            event = self._correction(entity_id, daylight=daylight, sleeping=sleeping)
            if event is None:
                continue
            logger.warning(
                f"Вечерний свет не соответствует решению ({event}): исправляю {entity_id}"
            )
            try:
                await self.engine.trigger(entity_id, event, respect_debounce=False)
            except Exception:  # noqa: BLE001 — одно устройство не мешает остальным
                logger.warning(f"Сверка вечернего света: {entity_id} не обработал {event}")

    def _sleeping(self) -> bool:
        """Спит ли дом по модификатору.

        Returns:
            True, только если модификатор «мы спим» включён; выключенное или
            неизвестное состояние — «не спим» (по неизвестному гасить нельзя).
        """
        value = (
            self._sleeping_supplier()
            if callable(self._sleeping_supplier)
            else self._sleeping_supplier
        )
        return value is True

    def _stops_on_sleep(self, entity_id: str) -> bool:
        """Гаснет ли этот свет по «мы спим» (параметр `off_by`).

        Args:
            entity_id: Автомат.

        Returns:
            True, если поведение задаёт `off_by: sleep`.
        """
        params = self.engine.definition_params(entity_id)
        return str(params.get("off_by", "")).strip().lower() == "sleep"

    def _correction(self, entity_id: str, *, daylight: bool, sleeping: bool) -> str | None:
        """Какое событие нужно автомату, чтобы совпасть с решением.

        В темноте при включённом «мы спим» свет с `off_by: sleep` должен быть
        **выключен** — именно этого не хватало: сверка видела «темно, а света
        нет» и включала гирлянду обратно через минуту после отбоя (боевой дефект
        2026-10-13). Теперь отбой учитывается: такой свет не возвращают, а если
        он всё же горит — сверка шлёт `sleep_started`.

        Args:
            entity_id: Автомат.
            daylight: Светло ли сейчас.
            sleeping: Включён ли модификатор «мы спим».

        Returns:
            Имя события либо ``None``, если расхождения нет.
        """
        state = self.engine.get_state(entity_id)
        if state is None:
            # Автомата нет: доставлять некому, но и молчать нельзя — журнал
            # покажет расхождение. Событие выбирается по времени суток.
            return "sunrise_started" if daylight else "sunset_started"
        is_on = state.current_state.upper().startswith("ON")
        if daylight:
            return "sunrise_started" if is_on else None
        if sleeping and self._stops_on_sleep(entity_id):
            return "sleep_started" if is_on else None
        return "sunset_started" if not is_on else None

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
