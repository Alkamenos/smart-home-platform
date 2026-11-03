"""Контекст собранной платформы (спека 018, US4).

Вынесен из composition root: контейнер собирает компоненты, а контекст —
результат сборки, которым пользуется приложение и тесты.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

from core.commands.dispatcher import CommandDispatcher
from core.control_tracker import ControlTracker
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.fsm.engine import FSMEngine
from core.models.manifest import Manifest


@dataclass
class PlatformContext:
    """Container for all platform components.

    Attributes:
        manifest: Loaded manifest with automation rules.
        event_bus: EventBus for publishing/subscribing to events.
        fsm: FSMEngine for state machine management.
        control_tracker: ControlTracker for tracking manual interventions.
        adapter: HAAdapter or MockAdapter for calling services.
        dispatcher: CommandDispatcher with middleware chain.
        event_router: EventRouter for routing sensor events to FSMs.
        fsm_bridge: Bridge delivering FSM transitions to persistence, Home
            Assistant mirror and live updates.
    """

    manifest: Manifest
    event_bus: EventBus
    fsm: FSMEngine
    control_tracker: ControlTracker
    adapter: Any  # HAAdapter or MockAdapter
    dispatcher: CommandDispatcher
    event_router: EventRouter
    fsm_bridge: Any = None
    watchdog: Any = None
    day_cycle: Any = None
    deco_watcher: Any = None
    #: Защита кондиционера: гасит охлаждение, недопустимое по правилам дома
    #: (зима, запрет владельца) — требование владельца 2026-10-15. В контексте,
    #: потому что shutdown() останавливает её до закрытия соединения с HA.
    ac_protection: Any = None
    #: Обход дома (BACKLOG F6): проблемы и реестр показаний по локациям и комнатам.
    house_health: Any = None
    deployment: Any = None
    #: Наблюдение за локациями (спека 016): последние показания датчиков и
    #: снимки. Нужно интерфейсу, чтобы отдавать снимок и историю.
    location_state: Any = None
    #: Зеркало снимков в Home Assistant через MQTT (спека 016).
    location_mirror: Any = None

    async def shutdown(self) -> None:
        """Idempotent shutdown: watchdog, adapter, FSM engine, dispatcher cleanup loop.

        Порядок важен: сторож читает состояния движка, поэтому он останавливается
        первым, а движок — после него (FR-017).
        """
        # ВИДИМО: shutdown() — единственный вызывающий adapter.stop() в рантайме
        # (#70). Запись нужна, чтобы отличить остановку по внешнему сигналу от
        # остановки внутри процесса; на info она не видна.
        logger.warning("Container.shutdown() called")
        if self.watchdog is not None:
            await self.watchdog.stop()
        # Суточный цикл останавливается до адаптера: он шлёт команды в HA, и
        # остановка соединения раньше расписания означала бы неотправленные
        # события в журнале отказа при штатном выключении.
        if self.day_cycle is not None:
            await self.day_cycle.stop()
            self.day_cycle = None
        # Сверка вечернего света — такой же фоновой исполнитель, как суточный
        # цикл: она тоже шлёт команды в HA, поэтому останавливается до адаптера.
        if self.deco_watcher is not None:
            await self.deco_watcher.stop()
            self.deco_watcher = None
        # Защита кондиционера тоже шлёт команду (гасит недопустимое охлаждение),
        # поэтому останавливается до закрытия соединения.
        if self.ac_protection is not None:
            await self.ac_protection.stop()
            self.ac_protection = None
        if self.house_health is not None:
            await self.house_health.stop()
            self.house_health = None
        await self.adapter.stop()
        await self.fsm.shutdown()
        await self.dispatcher.stop()


if TYPE_CHECKING:
    pass
