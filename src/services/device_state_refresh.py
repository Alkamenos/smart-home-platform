"""Сверка состояний устройств с источником истины после запуска (B62).

Состояние устройства — следствие Home Assistant, а не собственность снимка из
хранилища. Платформа восстанавливала состояния из ``devices.json``, где у штор
лежало **5 октября**, и показывала вчерашний день, пока сущность не сменит
состояние сама: шторы меняются раз в сутки, поэтому расхождение жило целыми
днями (боевая проверка 2026-10-14: платформа считала закрытыми три шторы, а
физически закрыта одна).

Связь с Home Assistant поднимается асинхронно, поэтому сверка идёт в фоне:
несколько попыток с паузой, пока источник не ответит. Сверка не задерживает
старт и не является ошибкой при молчании источника — она просто повторяется.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.logger import get_logger


logger = get_logger(__name__)


#: Пауза между попытками, пока источник не ответил.
DEFAULT_INTERVAL_SEC = 15.0

#: Сколько попыток сделать. 20 попыток по 15 секунд — пять минут: связь за это
#: время либо поднимается, либо её отсутствие уже видно сторожу отдельно.
DEFAULT_ATTEMPTS = 20


class DeviceStateRefresher:
    """Привести состояния устройств к Home Assistant после запуска.

    Args:
        device_service: Сервис устройств, принимающий состояния источника.
        adapter: Адаптер Home Assistant; ``None`` — сверять не с чем.
        interval_sec: Пауза между попытками.
        attempts: Сколько попыток сделать.
    """

    def __init__(
        self,
        device_service: Any,
        adapter: Any | None,
        interval_sec: float = DEFAULT_INTERVAL_SEC,
        attempts: int = DEFAULT_ATTEMPTS,
    ) -> None:
        self._device_service = device_service
        self._adapter = adapter
        self.interval_sec = interval_sec
        self.attempts = attempts
        self._task: asyncio.Task[None] | None = None

    def start(self) -> bool:
        """Запустить сверку в фоне.

        Синхронный метод намеренно: приложение собирается синхронно, а
        ожидаемая корутина без ``await`` там была бы ошибкой.

        Returns:
            True, если сверка запущена; False — нет работающего цикла событий.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Сверка состояний устройств не запущена: нет цикла событий")
            return False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return True

    def subscribe(self, event_bus: Any) -> bool:
        """Слушать восстановление связи с внешней системой.

        События, пропущенные во время обрыва, никто не повторит: подписка
        Home Assistant отдаёт только изменения. Поэтому после подключения
        состояния устройств приводятся к источнику заново (B62).

        Args:
            event_bus: Шина событий платформы.

        Returns:
            True, если подписка сделана.
        """
        subscribe = getattr(event_bus, "subscribe", None)
        if not callable(subscribe):
            return False
        from core.events.fsm_events import EVENT_HA_CONNECTED

        subscribe(EVENT_HA_CONNECTED, self._on_connected)
        return True

    async def _on_connected(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Привести состояния устройств к источнику после подключения.

        Args:
            event_type: Имя события (не используется).
            payload: Полезная нагрузка события (не используется).
            trace_id: Идентификатор трассы (не используется).
        """
        del event_type, payload, trace_id
        try:
            updated = await self.run_once()
        except Exception as exc:  # noqa: BLE001 — сверка не должна ронять шину
            logger.warning(f"Сверка состояний после подключения не удалась: {exc}")
            return
        if updated is None:
            logger.warning("Сверка состояний после подключения: источник не ответил")
            return
        logger.info(f"После подключения состояния устройств обновлены: изменено {updated}")

    async def run_once(self) -> int | None:
        """Одна попытка сверки.

        Returns:
            Сколько устройств изменило состояние; ``None`` — источник не
            ответил (повтор осмыслен, «ничего не изменилось» — нет).
        """
        reader = getattr(self._adapter, "get_all_states", None)
        if reader is None:
            return None
        states = await reader()
        if not states:
            return None
        updated = await self._device_service.apply_source_states(states)
        # Журнал ведётся loguru: в отличие от журнала сервиса устройств (stdlib,
        # INFO не виден в docker-журнале — урок #70), эта запись видна и
        # объясняет, откуда после старта взялись состояния устройств.
        logger.info(f"Состояния устройств приведены к Home Assistant: изменено {updated}")
        return updated

    async def _run(self) -> None:
        """Повторять сверку, пока источник не ответит."""
        for _ in range(max(self.attempts, 1)):
            try:
                updated = await self.run_once()
            except Exception as exc:  # noqa: BLE001 — фоновая сверка не должна умирать
                logger.warning(f"Сверка состояний устройств не удалась: {exc}")
                updated = None
            if updated is not None:
                return
            await asyncio.sleep(self.interval_sec)
        logger.warning(
            "Сверка состояний устройств: источник не ответил за "
            f"{self.attempts} попыток — состояния остаются из хранилища"
        )

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
