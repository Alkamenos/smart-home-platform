"""
Dependency Injection Container for Smart Home Platform.

This module provides a lightweight DI container with lazy initialization
for better modularity and testability.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from loguru import logger

from adapters.ha_adapter import HAAdapter
from adapters.mock_adapter import MockAdapter
from core.action_handlers import register_all_actions
from core.commands.dispatcher import CommandDispatcher
from core.commands.middleware import ManualLockoutMiddleware
from core.control_tracker import ControlTracker
from core.events.event_bus import EventBus
from core.events.event_router import EventRouter
from core.events.fsm_events import EVENT_PLATFORM_STARTED
from core.fsm.engine import FSMEngine
from core.fsm.factory import FSMFactory
from core.models.manifest import Manifest, load_manifest
from core.registry import Registry


@dataclass
class PlatformContext:
    """
    Container for all platform components.

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

    async def shutdown(self) -> None:
        """Idempotent shutdown: adapter, FSM engine, dispatcher cleanup loop."""
        await self.adapter.stop()
        await self.fsm.shutdown()
        await self.dispatcher.stop()


class Container:
    """
    Lightweight Dependency Injection Container with lazy initialization.

    This container creates and manages platform components, ensuring
    proper dependency ordering and enabling easy mocking for tests.

    Example usage:
        ```python
        container = Container(manifest_path="instances/leonids_house/manifest.yaml")
        context = container.build()

        # Or access components individually:
        engine = container.engine
        adapter = container.adapter
        ```
    """

    def __init__(
        self,
        manifest_path: str | None = None,
        manifest: Manifest | None = None,
        config_overrides: dict[str, Any] | None = None,
    ):
        """
        Initialize the DI container.

        Args:
            manifest_path: Path to the manifest YAML file.
            manifest: Pre-loaded manifest (alternative to manifest_path).
            config_overrides: Optional configuration overrides.
        """
        self._manifest_path = manifest_path
        self._manifest = manifest
        self._config_overrides = config_overrides or {}

        # Lazy-initialized components
        self._event_bus: EventBus | None = None
        self._fsm_bridge: Any | None = None
        self._fsm: FSMEngine | None = None
        self._control_tracker: ControlTracker | None = None
        self._event_router: EventRouter | None = None
        self._adapter: HAAdapter | MockAdapter | None = None
        self._dispatcher: CommandDispatcher | None = None
        self._middleware: ManualLockoutMiddleware | None = None
        self._registry: Registry | None = None
        self._factory: FSMFactory | None = None

    @property
    def manifest(self) -> Manifest:
        """Load and return the manifest (cached)."""
        if self._manifest is None:
            if self._manifest_path is None:
                msg = "Manifest path not provided"
                raise RuntimeError(msg)
            self._manifest = load_manifest(self._manifest_path)
        return self._manifest

    @property
    def event_bus(self) -> EventBus:
        """Get or create EventBus instance."""
        if self._event_bus is None:
            self._event_bus = EventBus()
        return self._event_bus

    @property
    def fsm(self) -> FSMEngine:
        """Get or create FSMEngine instance.

        Движок получает шину событий (публикует переходы) и хранилище состояний
        (FR-015). Диспетчер команд связывается отдельно в build(): он создаётся
        после движка, т.к. зависит от адаптера, а адаптер — от движка (R-01).
        """
        if self._fsm is None:
            self._fsm = FSMEngine(
                event_bus=self.event_bus,
                persistence=self._create_state_persistence(),
            )
        return self._fsm

    def _create_state_persistence(self) -> Any | None:
        """Создать хранилище состояний автоматов.

        Импорт выполняется внутри метода: пакет ``core.persistence`` тянет
        ``src.core.*``, что создаёт циклический импорт с контейнером.

        Returns:
            Экземпляр хранилища либо None, если хранилище создать не удалось.
        """
        try:
            from core.persistence.state_persistence import StatePersistence

            return StatePersistence()
        except (OSError, ImportError) as e:
            logger.warning(f"FSM state persistence unavailable: {e}")
            return None

    @property
    def control_tracker(self) -> ControlTracker:
        """Get or create ControlTracker instance."""
        if self._control_tracker is None:
            self._control_tracker = ControlTracker(history_size=100)
        return self._control_tracker

    @property
    def event_router(self) -> EventRouter:
        """Get or create EventRouter instance (depends on manifest and fsm)."""
        if self._event_router is None:
            self._event_router = EventRouter(manifest=self.manifest, engine=self.fsm)
        return self._event_router

    @property
    def adapter(self) -> HAAdapter | MockAdapter:
        """Get or create adapter instance (depends on fsm and event_router)."""
        if self._adapter is None:
            ws_url = os.environ.get("HA_WEBSOCKET_URL", "ws://localhost:8123/api/websocket")
            ha_token = os.environ.get("HA_TOKEN")

            if ha_token:
                self._adapter = HAAdapter(
                    mode="websocket",
                    engine=self.fsm,
                    event_router=self.event_router,
                    ws_url=ws_url,
                    token=ha_token,
                )
            else:
                self._adapter = MockAdapter(engine=self.fsm)
                self._adapter.set_event_router(self.event_router)
        return self._adapter

    @property
    def dispatcher(self) -> CommandDispatcher:
        """Get or create CommandDispatcher instance (depends on adapter)."""
        if self._dispatcher is None:
            self._dispatcher = CommandDispatcher(ha_adapter=self.adapter, middlewares=[])
            # Add middleware if available
            self._dispatcher.add_middleware(self.middleware)
        return self._dispatcher

    @property
    def middleware(self) -> ManualLockoutMiddleware:
        """Get or create ManualLockoutMiddleware instance."""
        if self._middleware is None:
            self._middleware = ManualLockoutMiddleware(
                automation_rules=self.manifest.automation_rules,
                control_tracker=self.control_tracker,
            )
        return self._middleware

    @property
    def registry(self) -> Registry:
        """Get or create Registry instance."""
        if self._registry is None:
            self._registry = Registry()
            register_all_actions(self._registry)
        return self._registry

    @property
    def factory(self) -> FSMFactory:
        """Get or create FSMFactory instance (depends on fsm, registry, event_bus)."""
        if self._factory is None:
            self._factory = FSMFactory(
                engine=self.fsm, registry=self.registry, event_bus=self.event_bus
            )
        return self._factory

    @property
    def fsm_bridge(self) -> Any:
        """Get or create FSMStateBridge (depends on event_bus, dispatcher).

        Мост доставляет каждый переход автомата потребителям состояния: журналу
        переходов, зеркалу Home Assistant и живым обновлениям (FR-015, FR-024).
        """
        if self._fsm_bridge is None:
            from services.fsm_state_bridge import FSMStateBridge

            self._fsm_bridge = FSMStateBridge(
                event_bus=self.event_bus,
                dispatcher=self.dispatcher,
                event_store=self._create_event_store(),
            )
        return self._fsm_bridge

    def _create_event_store(self) -> Any:
        """Создать журнал переходов и событий.

        Returns:
            Экземпляр журнала либо None, если журнал недоступен: отсутствие
            журнала не должно останавливать переходы автоматов (FR-003).
        """
        try:
            from core.persistence.event_store import EventStore

            return EventStore()
        except Exception as e:  # noqa: BLE001 - журнал не влияет на работу платформы
            logger.warning(f"Transition journal unavailable: {e}")
            return None

    async def announce_started(self) -> None:
        """Оповестить подписчиков о завершении инициализации платформы.

        Событие ``platform.started`` ожидают подписчики восстановления состояний
        и менеджер контекста; раньше оно не публиковалось никогда, поэтому эти
        подписчики были мертвы (FR-007).

        Returns:
            Ничего не возвращает; результат доставки логируется шиной.
        """
        await self.event_bus.publish(
            EVENT_PLATFORM_STARTED,
            {"manifest": str(self._manifest_path) if self._manifest_path else ""},
        )

    def build(self) -> PlatformContext:
        """
        Build and return the complete platform context.

        This triggers lazy initialization of all components in the correct order.

        Returns:
            PlatformContext with all initialized components.
        """
        # Access properties in dependency order to ensure proper initialization
        _ = self.event_bus  # No dependencies
        _ = self.fsm  # No dependencies
        _ = self.control_tracker  # No dependencies
        _ = self.factory  # Depends on fsm, registry, event_bus

        # Create and register FSMs from manifest BEFORE EventRouter:
        # EventRouter builds its sensor->FSM mapping once in __init__
        # from engine.get_entities_by_device(), so FSMs must already exist.
        self.factory.create_and_register(self.manifest)

        _ = self.event_router  # Depends on manifest, fsm (mapping built here)
        _ = self.adapter  # Depends on fsm, event_router
        _ = self.dispatcher  # Depends on adapter, middleware

        # Link dispatcher to FSM engine: the engine exists before the dispatcher
        # (dispatcher depends on adapter, adapter depends on engine), so the
        # cyclic dependency is broken here. Without this, CommandIntents from FSM
        # actions are dropped and automation never reaches devices (R-01, FR-016).
        self.fsm.set_command_dispatcher(self.dispatcher)

        # Start TTL cleanup loop when a running event loop exists
        # (sync build() in tests runs without a loop — start is skipped)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            self.dispatcher.start()

        # Link adapter to FSM engine
        self.adapter.set_fsm_engine(self.fsm)

        # Мост состояний: подписывается на переходы и обслуживает журнал,
        # зеркало Home Assistant и живые обновления (FR-015).
        _ = self.fsm_bridge

        return PlatformContext(
            manifest=self.manifest,
            event_bus=self.event_bus,
            fsm=self.fsm,
            control_tracker=self.control_tracker,
            adapter=self.adapter,
            dispatcher=self.dispatcher,
            event_router=self.event_router,
            fsm_bridge=self.fsm_bridge,
        )

    def reset(self) -> None:
        """Reset all cached instances for testing purposes."""
        self._event_bus = None
        self._fsm_bridge = None
        self._fsm = None
        self._control_tracker = None
        self._event_router = None
        self._adapter = None
        self._dispatcher = None
        self._middleware = None
        self._registry = None
        self._factory = None
        # Don't reset manifest as it's expensive to reload
