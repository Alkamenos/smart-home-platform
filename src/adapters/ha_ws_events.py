"""Event delivery for the Home Assistant WebSocket client (spec 018, T059).

Extracted from SimpleHAWebSocketClient: delivering accepted events and side
notifications without blocking the socket read loop.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

import asyncio
import logging
from typing import Any


logger = logging.getLogger("adapters.ha_websocket")


class HaWsEventsMixin:
    """Deliver events and one-shot notifications."""

    _event_queue: asyncio.Queue[dict[str, Any] | None]
    _event_handler: Any
    _filtered_out: int
    on_sleep_started: Any
    on_sleep_changed: Any
    on_sunset: Any
    on_sunrise: Any
    _pending_sleep_started: bool
    _pending_sleep_changed: bool
    _pending_sunset: bool
    _pending_sunrise: bool

    async def _deliver(self, payload: dict[str, Any]) -> None:
        """Передать событие обработчику, если оно проходит фильтр.

        Вынесено отдельно, чтобы доставка проверялась напрямую: события в бою
        приходят из сокета, и подмена пути скрыла бы, где именно теряется
        поток.

        Args:
            payload: Событие от HA.

        Returns:
            Ничего.
        """
        accepted = self._accepts(payload)
        # Переключение «мы спим» доносится до платформы до проверки фильтра:
        # сущность модификатора в подписку не входит, фильтр её отбрасывает
        # всегда, а гасить свет по включению модификатора — требование владельца
        # («свет над столом выключается по модификатору», 2026-10-09).
        if self._pending_sleep_started:
            self._pending_sleep_started = False
            notify = self.on_sleep_started
            if notify is not None:
                try:
                    await notify()
                except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                    logger.warning(f"HAAdapter: sleep_started не доставлен: {exc}")
        # Смена модификатора в любую сторону — тому, кто решает по флагам дома
        # (шторы и вентиляция): свет получает отдельное `sleep_started` выше, но
        # ему эта новость не нужна дважды.
        if self._pending_sleep_changed:
            self._pending_sleep_changed = False
            notify_changed = self.on_sleep_changed
            if notify_changed is not None:
                try:
                    await notify_changed()
                except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                    logger.warning(f"HAAdapter: смена «мы спим» не донесена: {exc}")
        # Закат и рассвет — по тому же пути и по той же причине: солнце вне
        # подписки, а вечернему освещению нужно знать о смене суток. Флаг живёт
        # одно событие, поэтому повторная доставка невозможна.
        for pending, callback, name in (
            ("_pending_sunset", self.on_sunset, "sunset"),
            ("_pending_sunrise", self.on_sunrise, "sunrise"),
        ):
            if not getattr(self, pending):
                continue
            setattr(self, pending, False)
            if callback is None:
                continue
            try:
                await callback()
            except Exception as exc:  # noqa: BLE001 — отказ уведомления не роняет поток событий
                logger.warning(f"HAAdapter: {name} не доставлен: {exc}")
        if not accepted:
            self._filtered_out += 1
            self._record_filtered_event()
            return
        if self._event_handler is not None:
            await self._event_handler(payload)

    async def _event_worker(self) -> None:
        """Разбирать очередь событий, пока её читает цикл сокета.

        Отдельная задача нужна для одной простой причины: команда, которую
        автоматика отправляет в ответ на событие, ждёт ответа Home Assistant —
        а ответ читает тот же цикл. Без раздельных задач чтение блокировалось
        до таймаута: в бою это означало 15 секунд задержки на каждое движение
        и потерю `context.id`, по которому своё действие отличается от
        действия человека (живой запуск 2026-10-08).

        Args:
            Ничего.

        Returns:
            Ничего. Задача живёт до отмены.
        """
        while True:
            payload = await self._event_queue.get()
            if payload is None:
                return
            try:
                await self._deliver(payload)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 — одно событие не роняет поток
                logger.warning(f"HAAdapter: ошибка обработки события: {e}")
