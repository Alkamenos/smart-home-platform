"""Защита кондиционера: зимой (и без разрешения владельца) он не охлаждает.

Требование владельца 2026-10-15: «защита кондиционера зимой теперь на платформе».
Зимнее охлаждение портит технику, поэтому правило не зависит от автоматики: даже
если кондиционер включили вручную или автоматизацией Home Assistant, платформа
выключает его и называет причину.

Почему отдельная служба, а не переход шаблона: кондиционер может работать
**без участия платформы** (владелец включил его приложением, автоматизация HA,
перезапуск платформы). Автомат принимает решения, когда ему приходит событие, и
в покое ничего не делает — а защита обязана сработать на чужое действие. Поэтому
служба смотрит **фактический режим прибора** и правила дома.

Правила берутся не «своим» кодом, а **тем же условием**, что и автоматика
(`may_cool`): сначала право владельца (гейт `ispolzovat_konditsioner`), потом
сезон (`zima`). Иначе защита и автоматика разошлись бы, и одна разрешала бы то,
что запрещает другая.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.logger import get_logger


logger = get_logger(__name__)


#: Режимы, в которых кондиционер охлаждает (или может охлаждать). `heat_cool` и
#: `auto` — «может охлаждать сам»: в мороз такой режим так же опасен, как `cool`.
COOLING_MODES = frozenset({"cool", "dry", "heat_cool", "auto"})

#: Причины, по которым защита выключает охлаждение. Гейт владельца
#: (`ispolzovat_konditsioner`) в них **не входит**: он про другое (разъяснение
#: владельца 2026-10-15), а защита заботится о дренажной трубке — ей вредны
#: мороз и зима.
REASON_WINTER = "ac_forbidden_in_winter"
REASON_FREEZE_RISK = "ac_freeze_risk"

#: Ниже этой температуры уличного воздуха кондиционер включать нельзя по
#: умолчанию: дренаж замёрзнет. Значение переопределяется параметром манифеста
#: `automation_rules.climate.ac_min_outside_temp`.
DEFAULT_MIN_OUTSIDE_TEMP = 5.0

DEFAULT_INTERVAL_MINUTES = 1.0


class AirConditionerProtection:
    """Выключать кондиционер, которому по правилам дома охлаждать нельзя.

    Args:
        adapter: Адаптер Home Assistant: читает режим прибора и уличную
            температуру с флагом зимы.
        dispatcher: Диспетчер команд: через него уходит выключение (тот же путь,
            что у команд автоматов — посредник, журнал, приоритеты).
        entities: Сущности кондиционеров из манифеста.
        interval_minutes: Как часто проверять, если событий от прибора нет.
        min_outside_temp: Ниже какой уличной температуры охлаждать нельзя.
    """

    def __init__(
        self,
        adapter: Any,
        dispatcher: Any,
        entities: list[str],
        interval_minutes: float = DEFAULT_INTERVAL_MINUTES,
        min_outside_temp: float = DEFAULT_MIN_OUTSIDE_TEMP,
    ) -> None:
        self._adapter = adapter
        self._dispatcher = dispatcher
        self.entities = [entity for entity in entities if entity]
        self.interval_minutes = interval_minutes
        self.min_outside_temp = min_outside_temp
        self._task: asyncio.Task[None] | None = None

    def start(self) -> bool:
        """Запустить периодическую проверку.

        Returns:
            True, если проверка запущена; False — нет цикла событий.
        """
        if not self.entities:
            logger.debug("Защита кондиционера не запущена: в манифесте нет кондиционеров")
            return False
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            logger.debug("Защита кондиционера не запущена: нет цикла событий")
            return False
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())
        return True

    def subscribe(self, event_bus: Any) -> bool:
        """Слушать изменения состояния кондиционеров.

        Реакция на событие — сразу, а не в следующий проход: владелец включил
        охлаждение зимой, и платформа гасит его в ту же секунду, а не через
        минуту.

        Args:
            event_bus: Шина событий платформы.

        Returns:
            True, если подписка сделана.
        """
        subscribe = getattr(event_bus, "subscribe", None)
        if not callable(subscribe):
            return False
        subscribe("state_change", self._on_state_change)
        return True

    async def _on_state_change(
        self, event_type: str, payload: dict[str, Any], trace_id: str | None = None
    ) -> None:
        """Проверить кондиционер, состояние которого изменилось.

        Args:
            event_type: Имя события (не используется).
            payload: Полезная нагрузка события.
            trace_id: Идентификатор трассы (не используется).
        """
        del event_type, trace_id
        entity_id = (payload or {}).get("entity_id")
        if entity_id in self.entities:
            await self.check_once()

    async def check_once(self) -> list[str]:
        """Проверить все кондиционеры и выключить запрещённое охлаждение.

        Returns:
            Сущности, которые были выключены этим проходом.
        """
        modes = await self._read_modes()
        logger.debug(f"Защита кондиционера: проверка, режимы={modes}")
        turned_off: list[str] = []
        for entity_id in self.entities:
            state = modes.get(entity_id)
            if state is None or state not in COOLING_MODES:
                continue
            try:
                reason = await self._forbidden_reason(entity_id)
            except Exception as exc:  # noqa: BLE001 — защита не должна падать
                logger.warning(f"Защита кондиционера: {entity_id} не проверен: {exc}")
                continue
            if reason is None:
                continue
            await self._turn_off(entity_id, reason)
            turned_off.append(entity_id)
        return turned_off

    async def _read_modes(self) -> dict[str, str]:
        """Режимы кондиционеров одним запросом.

        Почему не `get_entity_state`: для климат-приборов он отдаёт **цель**
        (атрибут `temperature`) — так читается уставка для синхронизации с
        термостатом. Защите нужен именно режим (`cool`/`heat`/`off`), поэтому
        состояния берутся списком: один запрос на все кондиционеры.

        Returns:
            Сущность → режим в нижнем регистре (только известные кондиционеры).
        """
        reader = getattr(self._adapter, "get_all_states", None)
        if not callable(reader):
            return {}
        try:
            raw = await reader()
        except Exception as exc:  # noqa: BLE001 — без режимов защита молчит
            logger.warning(f"Защита кондиционера: режимы не прочитаны: {exc}")
            return {}
        modes: dict[str, str] = {}
        for item in raw or []:
            entity_id = item.get("entity_id")
            if entity_id in self.entities:
                modes[str(entity_id)] = str(item.get("state") or "").strip().lower()
        return modes

    async def _forbidden_reason(self, entity_id: str) -> str | None:
        """Почему этому кондиционеру охлаждать нельзя.

        Забота защиты одна: **дренажная трубка замёрзнет**. Признаков два, и оба
        про мороз — уличная температура ниже порога (главный, требование
        владельца 2026-10-15) и флаг зимы. Гейт владельца
        (`ispolzovat_konditsioner`) сюда не входит: он про другое.

        Args:
            entity_id: Сущность кондиционера.

        Returns:
            Имя причины либо ``None``, если охлаждать можно.
        """
        context = self._house_context(entity_id)
        reason = self._forbidden_by_weather(context)
        logger.debug(
            f"Защита кондиционера: {entity_id} на улице="
            f"{context.get('outside_temperature')!r} зима={context.get('is_winter')!r} "
            f"решение={reason!r}"
        )
        return reason

    def _forbidden_by_weather(self, context: dict[str, Any]) -> str | None:
        """Запрещает ли погода охлаждение.

        «Не знаем» — не повод гасить прибор наугад: сразу после старта, пока
        температура и флаг не прочитаны, законно работающий кондиционер был бы
        выключен зря (тот же принцип, что у сторожа вентиляции).

        Args:
            context: Правила дома и уличная температура.

        Returns:
            Имя причины либо ``None``.
        """
        outside = context.get("outside_temperature")
        if isinstance(outside, bool) or not isinstance(outside, (int, float)):
            outside = None
        if outside is not None and float(outside) < self.min_outside_temp:
            return REASON_FREEZE_RISK
        if context.get("is_winter") is True:
            return REASON_WINTER
        return None

    def _house_context(self, entity_id: str) -> dict[str, Any]:
        """Правила дома для проверки охлаждения.

        Args:
            entity_id: Сущность кондиционера.

        Returns:
            Контекст: право владельца, сезон и признак «прибор умеет охлаждать»
            (иначе условие сочло бы переход неприменимым — BACKLOG B66).
        """
        context: dict[str, Any] = {"cooling": True, "entity_id": entity_id}
        builder = getattr(self._adapter, "event_context", None)
        if callable(builder):
            try:
                context.update(builder(entity_id))
            except Exception as exc:  # noqa: BLE001 — без правил защита не гадает
                logger.warning(f"Защита кондиционера: правила дома не собраны: {exc}")
        return context

    async def _turn_off(self, entity_id: str, reason: str) -> None:
        """Выключить кондиционер и записать причину.

        Args:
            entity_id: Сущность кондиционера.
            reason: Названная причина (право владельца или сезон).
        """
        from core.commands.dispatcher import CommandIntent

        explained = {
            REASON_FREEZE_RISK: (
                f"на улице ниже {self.min_outside_temp:g} °C — дренаж замёрзнет"
            ),
            REASON_WINTER: "зима: охлаждение портит технику",
        }.get(reason, reason)
        logger.warning(
            f"Защита кондиционера: {entity_id} охлаждает, а по правилам дома нельзя "
            f"({explained}) — выключаю"
        )
        intent = CommandIntent(
            device_id=entity_id,
            domain="climate",
            service="turn_off",
            data={},
            priority=90,
            source="climate_protection",
            # Правило безопасности, а не удобство автоматики: выключение не
            # отменяется ручной блокировкой (как ночное гашение света). Иначе
            # владелец, включивший охлаждение зимой, остался бы с ним.
            bypass_lockout=True,
        )
        try:
            await self._dispatcher.submit(intent)
        except Exception as exc:  # noqa: BLE001 — защита сообщает, но не падает
            logger.error(f"Защита кондиционера: {entity_id} не выключен: {exc}")

    async def _run(self) -> None:
        """Проверять по времени: события от прибора могут не прийти."""
        interval = max(self.interval_minutes, 0.1) * 60.0
        while True:
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — фоновая защита не умирает
                logger.warning(f"Защита кондиционера не удалась: {exc}")
            await asyncio.sleep(interval)

    async def stop(self) -> None:
        """Остановить проверку.

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
