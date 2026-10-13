"""Сторож вентиляции: периодически подтверждает решение автоматов.

Зачем нужен отдельный сторож. Решение вентиляции пересматривается по событию
датчика (`temperature_changed`) и по смене флагов дома (`settings_changed`). Но
рекуператор может «соскочить» с заданного режима сам: интеграция или прибор
меняют режим через пару минут после команды, а события датчика к этому моменту
нет. В бою 2026-10-13: платформа отправляла «Приток MAX», а через 2–5 минут
прибор снова стоял на «Рекуперации (зиме)», и до следующего показания датчика
вернуть его было нечем.

Сторож закрывает эту дыру: раз в интервал он просто шлёт автоматам вентиляции
`settings_changed` — тот же путь, что и смена флагов дома. Автомат сам решает,
что делать: жарко — подтвердить «Приток MAX», жара прошла — вернуть обычный
режим. Команда уходит, только если состояние действительно меняется.

Второе наблюдение того же дня (B54): прибор может быть **остановлен**, хотя
автомат считает себя в работе. Команда бывает принята Home Assistant
(«выполнен»), но не применена прибором — в бою кабинет включился только со
второй попытки. Подтверждение шлёт только режим, поэтому остановленный
рекуператор сам не поднимется. Сторож читает настоящее состояние прибора
(`get_entity_state`) и, если он `off`, сообщает автомату одноразовый факт
`_device_is_off`: шаблон сам решает, что это вход, и уходит с включением прибора.
Факт читает сторож, решение принимает шаблон — как и в остальных пересмотрах.

Интервал — минуты, а не секунды: сторож не должен превращаться в поток команд.
Значение по умолчанию — 5 минут: дрейф прибора заметен, а работы почти нет.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger

from core.fsm.engine import FSMEngine


#: Часть имени автомата, по которой отбираются автоматы вентиляции.
VENTILATION_MARKER = "_ventilation_modes_"


class VentilationWatchdog:
    """Подтверждать решение автоматов вентиляции по времени.

    Args:
        engine: Движок автоматов.
        interval_minutes: Как часто подтверждать решение. По умолчанию 5 минут.
        adapter: Адаптер Home Assistant для чтения состояния прибора. Без него
            сторож только подтверждает решение (как раньше): остановленный прибор
            он заметить не сможет.
    """

    def __init__(
        self,
        engine: FSMEngine,
        interval_minutes: float = 5.0,
        adapter: Any | None = None,
    ) -> None:
        self.engine = engine
        self.interval_minutes = interval_minutes
        self._adapter = adapter
        self._task: asyncio.Task[None] | None = None

    async def check_once(self) -> None:
        """Подтвердить решение каждого автомата вентиляции.

        Перед подтверждением читается настоящее состояние прибора: если он
        остановлен, автомат получает одноразовый признак ``_device_is_off``, и
        шаблон подтверждает решение включением, а не одним режимом.

        Returns:
            Ничего.
        """
        for entity_id in self.engine.entities_with_trigger("settings_changed"):
            if VENTILATION_MARKER not in entity_id:
                continue
            external_ctx = await self._device_off_context(entity_id)
            try:
                await self.engine.trigger(
                    entity_id,
                    "settings_changed",
                    external_ctx=external_ctx,
                    respect_debounce=False,
                )
            except Exception:  # noqa: BLE001 — один автомат не мешает остальным
                logger.warning(f"Сторож вентиляции: {entity_id} не обработал подтверждение")

    async def _device_off_context(self, entity_id: str) -> dict[str, Any] | None:
        """Прочитать состояние прибора и назвать остановку.

        Args:
            entity_id: Идентификатор автомата вентиляции.

        Returns:
            ``{"_device_is_off": True}``, если прибор остановлен, иначе ``None``.
            Неудача чтения — тоже ``None``: молчание прибора не повод слать
            команду, а следующая проверка повторит попытку.
        """
        if self._adapter is None:
            return None
        device = self.engine.device_id_of(entity_id)
        if not device:
            return None
        try:
            state = await self._adapter.get_entity_state(device)
        except Exception as exc:  # noqa: BLE001 — чтение не должно ронять сторожа
            logger.warning(f"Сторож вентиляции: состояние {device} не прочитано: {exc}")
            return None
        if state is None or str(state).strip().lower() != "off":
            return None
        logger.info(
            f"Сторож вентиляции: прибор {device} остановлен — "
            f"{entity_id} подтвердит решение включением"
        )
        return {"_device_is_off": True}

    async def _run(self) -> None:
        """Подтверждать решение до остановки.

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
            except Exception as exc:  # noqa: BLE001 — фоновый сторож не должен умирать
                logger.warning(f"Сторож вентиляции не удался: {exc}")

    def start(self) -> None:
        """Запустить сторожа в фоне.

        Returns:
            Ничего.
        """
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
            logger.info(f"Сторож вентиляции: подтверждение каждые {self.interval_minutes:g} мин")

    async def stop(self) -> None:
        """Остановить сторожа.

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
        """Описание сторожа для журнала и готовности.

        Returns:
            Словарь с интервалом и признаком работы.
        """
        return {
            "interval_minutes": self.interval_minutes,
            "running": self._task is not None and not self._task.done(),
        }
